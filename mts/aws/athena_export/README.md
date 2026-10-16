# Step 1: Athena to S3 as CSV

`export_mts_table_1.sql` through `export_mts_table_9.sql` each export one MTS
table with columns in the same order as its
PostgreSQL DDL. Athena SELECT writes a CSV with a header to the workgroup's
results bucket. This uses Athena's native CSV output and does not require a
JSON conversion or a Glue job.

## Run all nine exports

Install boto3 if needed (`python -m pip install boto3`) and authenticate with your
usual AWS profile. From the repository root:

```powershell
python local_data/athena_export/export_all_mts.py --region us-east-1 --profile your-profile --s3-prefix s3://YOUR-RESULTS-BUCKET/queries/postgres-exports/
```

Replace the bucket with your stack's `AthenaResultsBucketName`. Using its
`queries/` prefix fits the existing Athena query policy. The script runs the
SELECT files, waits for completion, and copies the generated CSVs within S3
into a fresh timestamped folder with these filenames:

```text
mts_table_1_export.csv
mts_table_2_export.csv
...
mts_table_9_export.csv
```

Only use a run after the export command finishes successfully; a failed run
may leave partial exports. Reruns use new
folders. No files are downloaded by this step. Athena's original query-result
files also remain in S3.

Override `--catalog`, `--namespace`, or `--workgroup` if your stack names differ.
The all-table entry point always exports all nine tables. For a single-table
check, use `tools/mts_postgres/export_athena_csv.py` with `--tables mts_table_1`,
or run an individual SQL file in Athena. `--timeout` controls the
per-query timeout in seconds (default 900).

The workgroup enforces its query-result location, so the routine reads Athena's
actual output location before copying. It needs the existing Athena read/query
permissions plus S3 read access to results and write access to the export
prefix. Destinations use SSE-S3 encryption; bucket policies requiring a different
encryption mode need an explicit configuration change. Athena queries, S3
copies, and storage incur their usual charges. This export adds no infrastructure.

Keep ingestion and other source writers idle until all exports finish; separate
table queries do not form a cross-table snapshot.

## Run an individual export in the Athena console

Select your MTS workgroup, catalog, and namespace, then paste the relevant SQL
file into the query editor and run it. Athena places the CSV in its results
bucket under the query ID. Copy or rename that object to `mts_table_N_export.csv` if
you want the same naming as the routine.

## Next step: simple PostgreSQL loading

After downloading a CSV, loading can use a single psql command per table:

```sql
\copy mts.mts_table_1 FROM 'mts_table_1_export.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
```

This example appends rows to an existing empty table. To replace all nine tables,
use `local_data/load_mts_data.sql`, which wraps truncation and the nine CSV copy
commands in one transaction. See the [load instructions](../README.md).
Confirm a live export's NULL and empty-string behavior before
using it for your first full import; a live AWS/PostgreSQL smoke test has not
been performed here.

Reference: [Athena SELECT produces CSV](https://docs.aws.amazon.com/athena/latest/ug/unload.html).
