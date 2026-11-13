# Run the MTS Glue load job

[`mts_to_tables.py`](mts_to_tables.py) loads Monthly Treasury Statement (MTS)
JSON feeds into nine Iceberg tables in an S3 table bucket: `mts_table_1` through
`mts_table_9`. It runs as an AWS Glue 5.0 Spark ETL job.

## Deploy with PowerShell

From the repository root, run this with the AWS CLI configured:

```powershell
./mts/aws/glue/mts_load/deploy_mts_glue_load.ps1 -Region us-east-2 -CodeBucketName 'your-existing-code-bucket' -Version 'v1.2.0-rc1'
```

The script uploads `mts_to_tables.py` and `mts_pre_march_2015_transform.py`
to `glue/mts_load/v1.2.0-rc1/` and deploys the lakehouse stack with both S3 keys.
Use a new version when either file changes. A version must start with a letter
or digit and can also contain periods, underscores, and hyphens. A version
containing only digits keeps the existing naming convention, so `1` uses
`v1/`. The default stack name is
`MTS-Lakehouse`. Use `-StackName` or `-Profile` if your deployment differs.

For an existing stack, use its current `GlueScriptBucketName` as
`-CodeBucketName`. The deployment retains existing values for the other
stack parameters, including the export configuration. For a new stack, those
parameters take the template defaults. See the lakehouse README for custom
stack settings.

## Prerequisites

- Deploy the [MTS lakehouse stack](../../mts_lakehouse/mts_lakehouse_iac.yaml).
  See the [lakehouse README](../../mts_lakehouse/README-lakehouse_for_mts_data.md)
  for deployment details. The stack creates the job, execution role, table bucket,
  namespace, and CloudWatch log groups.
- For manual deployment, upload this directory's `mts_to_tables.py` to the
  same-region script bucket configured by `GlueScriptBucketName`. Set
  `GlueScriptObjectKey` to its exact object key. For updates, upload to a new
  immutable key and update that stack parameter.
- For raw or previously staged archive reports, upload [`mts_pre_march_2015_transform.py`](mts_pre_march_2015_transform.py)
  to the same script bucket. Keep the filename and use a versioned folder.
  Set `ArchiveTransformObjectKey` to the full object key. The stack adds
  the module to the Glue job's Python files.
- Make sure the reports to load already exist in the configured feeds bucket.
  The [MTS downloader](../../lambda/mts_download/README-mts_download_lambda.md)
  produces the source feeds and manifests. This job does not download missing
  reports from Treasury.
- Use an AWS identity authorized to start and inspect the Glue job. CLI examples
  also require an installed, configured AWS CLI.

The stack's `GlueJobName` output identifies the deployed job, normally
`<stack-name>-mts-load`. Its `SourceBucketName`, `TableBucketArn`, and `Namespace`
outputs identify the input bucket and destinations. The default namespace is
`silver_mts`.

## Choose the reports to load

The lakehouse stack can run this job automatically after its scheduled download
succeeds. The workflow passes the downloaded month's prefix to Glue.
See [scheduled workflow setup](../../mts_lakehouse/README-lakehouse_for_mts_data.md#scheduled-monthly-download-and-load).

Supply `--base_prefix` or both `--start_date` and `--end_date`. The prefix is
bucket-relative and can end with a slash.

| Value | Reports selected |
| --- | --- |
| `mts/2026/08` | August 2026 only. |
| `mts/2025` | All available months in 2025. |
| `mts` | All available months across all years. |

The date bounds use `YYYY-MM-DD` and include reports whose calendar month-end
falls on or between them. For example, `2025-01-01` through `2025-03-31`
selects January through March 2025. With dates alone, the job searches under
`mts/`. With a prefix and dates, both must match.

The job recursively lists the prefix, follows all listing pages, and selects
`mts/YYYY/MM/manifest.json` objects in sorted key order. Other feed JSON files
are not selected directly. Missing months are skipped; finding no manifests is
an error. An unexpected manifest location also causes an error.

The manifest identifies the source objects for the month. New downloads
store the original Treasury bytes under `mts/YYYY/MM/raw/`. New archive
manifests point to the nine transformed table JSON files in the month
folder. Previously staged manifests may point to a STAR text file or to
nine table JSON files. API manifests point to the original JSON pages for
all nine tables.

The loader verifies source hashes, parses the archive text, and maps its
amounts and sequence fields into the MTS schema. For API pages it validates
the schema and page totals, then combines the rows for each table. It
validates and converts source rows before writing the report. Each source
object, including the manifest, is limited to 32 MiB.

The loader normalizes `classification_desc` to title case across all nine
tables. For example, `RECEIPTS` and `Receipts` both load as `Receipts`.
Classification IDs retain their source values. After deploying the updated
script, rerun the affected report months to normalize rows already in Iceberg.
You can use the staged feeds for those runs.

For Table 9, the loader derives API-compatible sequence numbers, sequence
levels, and record types for raw STAR reports and previously staged STAR JSON.
After deploying both loader files, rerun October 1997 through February 2015
in batches to backfill the fields, then refresh exports and reports.

Deploy this loader and its archive module before updating the bulk downloader
or the scheduled Lambda. To regenerate the nine table JSON files for an
archive month, redownload that month, then rerun the load.

## Run from the AWS console

1. Open AWS Glue in the account and region containing the lakehouse stack.
2. Open **ETL jobs** and select the job from the `GlueJobName` stack output.
3. Choose **Run with parameters**. Set both date values for a bounded run and
   leave `--base_prefix` at `REQUIRED` to search all years. For a prefix-only
   run, set `--base_prefix` (for example, `mts/2026/08`) and leave both dates
   at `unset`.
4. Start the run, then open its run details to monitor status and logs.
5. Wait for `SUCCEEDED` before consuming the loaded reports.

The stack permits one concurrent run and configures no automatic retries. It
defaults to two `G.1X` workers and a 30-minute timeout. For long backfills,
increase `GlueTimeoutMinutes` on the stack before running; `WorkerCount` is also
configurable.

## Run with the AWS CLI (PowerShell)

Run these commands with your deployed job name and region. The JSON argument
file avoids differences in shell handling of inline JSON.

```powershell
$jobName = 'accountableguv-mts-lakehouse-mts-load'
$region = 'us-east-1'
$argumentsPath = Join-Path ([System.IO.Path]::GetTempPath()) 'mts-load-arguments.json'
'{"--start_date":"2025-01-01","--end_date":"2025-03-31"}' | Set-Content -LiteralPath $argumentsPath -Encoding ascii

$runId = aws glue start-job-run `
  --job-name $jobName `
  --arguments "file://$argumentsPath" `
  --region $region `
  --query JobRunId `
  --output text

aws glue get-job-run `
  --job-name $jobName `
  --run-id $runId `
  --region $region `
  --query 'JobRun.{State:JobRunState,Error:ErrorMessage,Started:StartedOn,Completed:CompletedOn}'
```

Repeat `get-job-run` to check progress. For a prefix-only run, replace the
date arguments with `"--base_prefix":"mts/2025"` or `"--base_prefix":"mts"`.

## Job configuration and arguments

The stack configures these required script arguments as non-overridable:

| Argument | Stack configuration |
| --- | --- |
| `--feeds_bucket` | `FeedsBucketName`, or `acctguv-feeds-<region>` when empty. |
| `--table_bucket_arn` | ARN of the stack's S3 table bucket. |
| `--namespace` | `MtsNamespace`, default `silver_mts`. |
| `--region` | Stack region. |
| `--rest_endpoint` | Regional S3 Tables Iceberg REST endpoint. |

Glue supplies `JOB_NAME`. The stack also enables the bundled Iceberg runtime
with `--datalake-formats=iceberg`, configures Iceberg Spark extensions and UTC,
and disables job bookmarks. No external JAR or additional Python module upload
is required by this configuration. Use the template's settings and execution
role permissions if creating a job manually.

`--manifest_key` and `--manifest_version_id` are not supported run arguments.
Manifest keys and versions are recorded as lineage in the output tables.

## Verify a run and recover from failures

Use the Glue run's CloudWatch log links, or the stack's `ErrorLogGroup` and
`OutputLogGroup` outputs. The configured groups are
`/aws-glue/<stack-name>/mts/error` and `/aws-glue/<stack-name>/mts/output`.
Look for:

- `Selected ... manifests` for the discovered report count.
- `Loaded s3tables.<namespace>.mts_table_...` for each table's checked row count.
- `Completed manifest=... report_date=... batch_id=...` for each completed report.
- `Completed all ... reports` and Glue status `SUCCEEDED` for overall success.

Tables are created automatically with an identity partition on `record_date`.
Each load replaces that report date in each table and preserves other dates.
Rerunning a prefix does not append duplicate rows, and corrections remove rows
that disappeared from the revised source. Reruns do create new snapshots and
ingestion timestamps. Rows include source object/hash/version information,
manifest lineage, a manifest-hash batch ID, and transformation version.

Replacement is atomic per table, **not across all nine tables**. A failure stops
the run; earlier completed months remain loaded, and the failing month may have
only some tables updated. Resolve the error and rerun the failing month's prefix
or the original prefix to replace the affected data. Avoid other writers during
the load, and wait for the complete run to succeed before using its results.

| Error or symptom | Action |
| --- | --- |
| Invalid prefix / default `REQUIRED` | Set a supported `--base_prefix` or supply both date bounds. |
| No MTS manifests found | Check the configured feeds bucket and prefix; run the downloader if feeds are missing. |
| SHA-256, row-count, or report-date mismatch | Check that the month has a complete, consistent feed and manifest; regenerate the complete report if needed. |
| Source schema changed / target schema differs | Review the source schema or explicitly migrate the target schema before retrying. The loader does not alter existing schemas automatically. |
| Access denied | Check the Glue execution role's source-list/read, source-version-read, script-read, S3 Tables, and log permissions against the template. |
| Timeout | Rerun the affected reports in smaller date ranges or increase `GlueTimeoutMinutes`. |

For optional Athena verification and its separate catalog integration setup,
see [Query the MTS tables with Athena](../../mts_lakehouse/README-lakehouse_for_mts_data.md#query-the-mts-tables-with-athena).
