# Local PostgreSQL tables and Athena CSV load

`create_mts_table_1.sql` through `create_mts_table_9.sql` create the tables in schema `mts`.
`load_mts_table_1.sql` through `load_mts_table_9.sql` each create a missing table
and load its matching Athena CSV. `load_mts_data.sql` calls all nine loaders in
one transaction. The [lakehouse Glue export job](../../aws/mts_lakehouse/README-lakehouse_for_mts_data.md)
generates the Athena CSVs.

## Run the Glue export and load PostgreSQL

With the lakehouse export job deployed, run this from the repository root:

```powershell
./mts/local_data/mts_load_to_postgres/load_exports.ps1 -Profile YOUR-AWS-PROFILE
```

The script starts `MTS-Lakehouse-mts-export` in `us-east-2` and waits for
that run to reach `SUCCEEDED`. It downloads all nine CSVs from the job's
configured `--output_s3` folder, then loads them in one PostgreSQL transaction.
The default database is `mts` with user `postgres` on `localhost:5432`.
After the load succeeds, the CSVs are saved to `mts/local_data/mts_export`.

Omit `-Profile` to use default AWS credentials. Use `-Region` and
`-ExportJobName` if your deployment differs. Find the job name in the
lakehouse stack's `ExportGlueJobName` output. You can also override
`-Database`, `-DbUser`, `-DbHost`, `-DbPort`, or `-CsvDirectory`.
If you pass `-S3Prefix`, it must match the job's configured export folder.

AWS CLI and psql must be installed. The script also finds PostgreSQL 18 at its
standard Windows installation path; `-PsqlExecutable` can specify another full
path. PostgreSQL uses its password file or prompts for your password. Your AWS
identity needs `glue:GetJob`, `glue:StartJobRun`, `glue:GetJobRun`, and
`glue:GetJobRuns` on the export job, plus S3 read access to the CSVs.
If Glue fails, a CSV download fails, or a newer run of the job is detected
during download, the script stops before invoking PostgreSQL. Download or
load failures leave the `.download-*` folder for inspection. PostgreSQL
output is saved to `postgres_load.log` in the CSV directory.

## Load existing CSVs with psql

Pass the CSV folder using `-v csv_dir="..."`. It works from any current directory
and supports folder names containing spaces. For all nine tables:

```powershell
psql -X -h localhost -p 5432 -U postgres -d mts -v csv_dir="C:/Data/MTS exports" -f 'C:\GitHub Repos\accountableguv\mts\local_data\mts_load_to_postgres\load_mts_data.sql'
```

Use your PostgreSQL installation's full `bin\psql.exe` path if needed. The
client-side `\copy` commands require psql rather than pgAdmin's Query Tool.
DDL includes resolve relative to the script; CSV files resolve relative to the
folder supplied by `csv_dir`. If omitted, they resolve relative to the current
working directory as before. The loaders change psql's working directory before
loading; use an absolute folder path for clarity. No JSONL files or manifest are required by the loader.
Each CSV must have its Athena header and the export SQL's column order.

To create and load only one table, pass the folder to its individual script:

```powershell
psql -X -h localhost -p 5432 -U postgres -d mts -v csv_dir="C:/Data/MTS exports" -f 'C:\GitHub Repos\accountableguv\mts\local_data\mts_load_to_postgres\load_mts_table_1.sql'
```

Each individual script includes its matching `CREATE TABLE IF NOT EXISTS` DDL,
replaces that table's rows, and commits the load in its own transaction. Only
that table's CSV is required. The combined loader manages one shared transaction
using the reserved psql variable `mts_load_all`; do not set that variable when
running an individual script directly.

**Loading replaces every row in all nine tables.** DDL, truncation, and the nine
COPY commands run in one transaction. Missing files, malformed CSV, or invalid
values stop psql and roll back when the connection closes. Truncation does not
cascade to dependent tables. Keep other local writers idle. Existing tables must
match the supplied DDL.

PostgreSQL CSV rules treat unquoted empty fields as NULL and quoted empty fields
as empty strings. Decimals load directly into numeric columns, identifiers into
text, and ingestion timestamps into UTC-valued timestamp columns. This simple
loader skips the header and does not verify header names, counts, or checksums.
A live Athena/PostgreSQL smoke test is still needed, including NULL and empty
string checks.

```sql
SELECT record_date, count(*)
FROM mts.mts_table_1
GROUP BY record_date
ORDER BY record_date;
```
