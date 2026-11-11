# Export MTS tables to CSV with AWS Glue

The lakehouse's Glue 5.0 export job uses [`export_mts_csv.py`](export_mts_csv.py)
to query all nine MTS tables through Athena. It runs one query per table and
waits for all nine queries to succeed before copying the results to
`mts_table_1_export.csv` through `mts_table_9_export.csv`. Each successful
run replaces those same S3 objects. Use the files after the job run reaches
`SUCCEEDED`.

## Enable the export job

1. Upload `export_mts_csv.py` to the S3 bucket configured as
   `GlueScriptBucketName`. Use a new object key when updating the script.
2. Deploy or update the [lakehouse CloudFormation template](../../mts_lakehouse/mts_lakehouse_iac.yaml).
   Set `ExportScriptObjectKey` to the uploaded object's key and keep the
   existing lakehouse parameter values. The stack creates the export job,
   execution role, and CloudWatch log groups.
3. Find the job name in the stack's `ExportGlueJobName` output and the CSV
   destination in `MtsExportLocation`. The default destination is
   `s3://acctguv-feeds-<region>/exports/mts_exports/`. The stack's
   `FeedsBucketName` and `ExportPrefix` parameters control that location.

## Run the export

In AWS Glue Studio, open the job named in `ExportGlueJobName` and choose
**Run**. The stack supplies the Athena workgroup, catalog, namespace, and
output location. For the `MTS-Lakehouse` stack in `us-east-2`, the equivalent
AWS CLI command is:

```powershell
aws glue start-job-run --job-name MTS-Lakehouse-mts-export --region us-east-2
```

Check the run status in Glue Studio. The run details link to CloudWatch
logs, where the job records the Athena query IDs and the exported S3 paths.

## Export, download, and load into local PostgreSQL

Use [`load_exports.ps1`](../../../local_data/mts_load_to_postgres/load_exports.ps1)
to start the export, wait for that run to succeed, download the nine CSVs
from the job's configured S3 location, and load them into PostgreSQL in
one transaction. Run it from the repository root:

```powershell
./mts/local_data/mts_load_to_postgres/load_exports.ps1 -Profile YOUR-AWS-PROFILE
```

The script defaults to `MTS-Lakehouse-mts-export` in `us-east-2`. See the
[local PostgreSQL import README](../../../local_data/mts_load_to_postgres/README-local_import_mts_data.md)
for prerequisites, AWS permissions, and connection options.
