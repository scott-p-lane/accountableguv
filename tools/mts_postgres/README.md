# Export MTS S3 Tables to local PostgreSQL

For the simpler two-step CSV workflow, start with
[Athena-to-S3 CSV export](../../local_data/athena_export/README.md).
The JSONL bundle workflow below remains available separately.

This routine exports the nine loaded MTS tables using the lakehouse's existing
Athena workgroup, then imports the saved bundle with PostgreSQL's bulk `COPY`
protocol. No Glue export job or new AWS infrastructure is required. Export and
load are separate commands: a bundle can be reused offline without AWS access.
Python 3.10+ and an existing PostgreSQL database are required.

## Setup (PowerShell, repository root)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r tools/mts_postgres/requirements.txt
```

Use the catalog integration and query permissions described in the
[lakehouse setup](../../aws_iac/cloud-formation-templates/mts_lakehouse/README.md#query-the-mts-tables-with-athena).
Authenticate using your usual AWS credentials; for an SSO profile run
`aws sso login --profile your-profile` first. The script uses the standard AWS
credential chain. Omit `--profile` to use its default credentials.

## Export

```powershell
.venv\Scripts\python tools/mts_postgres/mts_postgres.py export --region us-east-1 --profile your-profile --bundle exports/mts-2026-10-05
```

The bundle directory must be new. Override `--catalog`, `--namespace`, and
`--workgroup` with the corresponding CloudFormation outputs if your stack uses
different names. To select tables, append `--tables mts_table_1 mts_table_2`.
The default exports all rows and columns from all nine tables, including lineage.
Each query has a 900-second timeout; override with `--timeout`. Timed-out and
interrupted active queries are cancelled.

Wait for ingestion to finish and keep writers idle during export. Each Athena
query reads its own table snapshot; the nine queries do not provide a single
cross-table snapshot. Athena scan charges, the workgroup's scan limit, and its
S3 result-storage charges apply. This paginated export is intended for the
project's modest monthly MTS data, rather than very large lakehouse datasets.

The output contains one UTF-8 JSON Lines file per table and a final manifest with
column types, row counts, checksums, and Athena query IDs. Values retain Athena's
exact string representation, while JSON null represents SQL NULL. This avoids
confusing empty strings or literal `null` / `\N` text with SQL NULL. A failed
export leaves an incomplete directory without a manifest; retry into a new
directory. Store bundles outside Git (the `exports/` directory is ignored).

## Load into PostgreSQL

Create an empty local database, for example `accountableguv`, using your usual
PostgreSQL administration tool. Set the connection string locally:

```powershell
$env:MTS_POSTGRES_DSN = 'host=localhost port=5432 dbname=accountableguv user=postgres'
.venv\Scripts\python tools/mts_postgres/mts_postgres.py load --bundle exports/mts-2026-10-05
```

Use PostgreSQL's password file (`%APPDATA%\postgresql\pgpass.conf`) or supply
your password through your local connection configuration. The connection string
is read from the environment, not a command-line argument. `--dsn-env` changes
the environment variable name. `--schema` changes the default destination `mts`.
The database user needs permission to create the schema/tables and truncate,
copy, and select the destination tables.

**Loading replaces all rows in the bundle's selected destination tables.** It
creates missing tables and verifies existing column names, order, and types
before truncating. It refuses schema drift and does not cascade to dependent
tables. All selected tables load in one transaction; malformed data, checksum
errors, type errors, or failed row-count checks roll back the entire import.
Unselected tables are untouched. Rerunning a bundle does not append duplicates.
Do not run competing local writers during import; truncation takes table locks.

Decimals become `numeric(38,2)` without floating-point conversion. String
identifiers remain text, dates remain dates, and the source UTC ingestion
timestamp remains `timestamp without time zone`, matching the lakehouse schema.
The routine does not invent primary keys, relationships, or indexes.

```sql
SELECT record_date, count(*)
FROM mts.mts_table_1
GROUP BY record_date
ORDER BY record_date;
```

## Checks

```powershell
python -m unittest discover -s tools/mts_postgres/tests -v
```

Tests cover export pagination, NULL/text fidelity, exact decimal strings,
empty tables, incomplete exports, query cancellation, and bundle integrity.
For a live smoke test, export one table, load it into an isolated schema such as
`--schema mts_smoke`, compare its count with the manifest, and rerun the load.
AWS and PostgreSQL access are needed for that smoke test.

API references: [Athena query results](https://docs.aws.amazon.com/botocore/latest/reference/services/athena/client/get_query_results.html)
and [Psycopg bulk COPY](https://www.psycopg.org/psycopg3/docs/basic/copy.html).
