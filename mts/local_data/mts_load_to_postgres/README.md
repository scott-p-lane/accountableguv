# Local PostgreSQL tables and Athena CSV load

`create_mts_table_1.sql` through `create_mts_table_9.sql` create the tables in schema `mts`.
`load_mts_table_1.sql` through `load_mts_table_9.sql` each create a missing table
and load its matching Athena CSV. `load_mts_data.sql` calls all nine loaders in
one transaction. These scripts load CSV files from
[the Athena exports](athena_export/README.md).

## Export and download

From the repository root, with boto3 installed and AWS credentials configured:

```powershell
python local_data/athena_export/export_all_mts.py --region us-east-1 --profile your-profile --s3-prefix s3://YOUR-RESULTS-BUCKET/queries/postgres-exports/
```

Wait for the export job or command to finish successfully, then download:

```powershell
aws s3 cp s3://YOUR-RESULTS-BUCKET/queries/postgres-exports/RUN-FOLDER/ exports/mts-download/ --recursive --exclude '*' --include '*.csv' --profile your-profile --region us-east-1
```

Replace bucket, run folder, profile, and region with your actual values. The nine
individual Athena SQL scripts remain available for individual exports.

## Load with psql

To download the completed S3 exports into `mts/local_data/mts_export` and load
all nine tables in one command, run this from the repository root:

```powershell
./mts/local_data/mts_load_to_postgres/load_exports.ps1 -Profile YOUR-AWS-PROFILE
```

Defaults are S3 `s3://acctguv-feeds-us-east-2/exports/mts_exports/`, region
`us-east-2`, and PostgreSQL database `mts` with user `postgres` on
`localhost:5432`. Omit `-Profile` to use default AWS credentials. Override
`-Database`, `-DbUser`, `-DbHost`, `-DbPort`, or `-CsvDirectory` as needed:

```powershell
./mts/local_data/mts_load_to_postgres/load_exports.ps1 -Profile YOUR-AWS-PROFILE -Database mts -CsvDirectory './mts/local_data/mts_export'
```

AWS CLI and psql must be installed. The script also finds PostgreSQL 18 at its
standard Windows installation path; `-PsqlExecutable` can specify another full
path. PostgreSQL uses its password file or prompts for your password. Your AWS
identity needs S3 read access to the export objects. The download checks the
successful download of all nine CSVs; if any download fails, it stops before
loading the database. Run this only after Glue succeeds and while no new export
is running, since the script does not check for concurrent export changes. Failed
downloads leave a `.download-*` folder for inspection. Successful downloads
replace local export copies and invoke the combined SQL loader, which replaces
all nine database tables in one transaction.

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
