# Run the MTS Glue load job

[`mts_to_tables.py`](mts_to_tables.py) loads Monthly Treasury Statement (MTS)
JSON feeds into nine Iceberg tables in an S3 table bucket: `mts_table_1` through
`mts_table_9`. It runs as an AWS Glue 5.0 Spark ETL job.

## Prerequisites

- Deploy the [MTS lakehouse stack](../../mts_lakehouse/mts_lakehouse_iac.yaml).
  See the [lakehouse README](../../mts_lakehouse/README-lakehouse_for_mts_data.md)
  for deployment details. The stack creates the job, execution role, table bucket,
  namespace, and CloudWatch log groups.
- Upload this directory's `mts_to_tables.py` as a plain Python file to the
  same-region script bucket configured by `GlueScriptBucketName`. Set
  `GlueScriptObjectKey` to its exact object key. For updates, upload to a new
  immutable key and update that stack parameter.
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

To load reports automatically after scheduled downloads, set `MtsGlueJobName`
on the feeds staging stack to the lakehouse stack's `GlueJobName` output.
The [feeds workflow instructions](../../../../aws_shared/for_feed_staging/README-feeds_staging_iac_.md#automatically-load-downloaded-mts-reports)
explain deployment and monitoring. The workflow supplies the downloaded month's
prefix and starts Glue only after the downloader succeeds.

Supply `--base_prefix` on every run. It is a bucket-relative prefix, without
`s3://` or the bucket name. A trailing slash is optional.

| Value | Reports selected |
| --- | --- |
| `mts/2026/08` | August 2026 only. |
| `mts/2025` | All available months in 2025. |
| `mts` | All available months across all years. |

Only these three prefix forms are supported: `mts`, `mts/YYYY`, and
`mts/YYYY/MM` (two-digit month `01` through `12`). There is no start/end-date
argument. Run individual month prefixes for a custom range.

The job recursively lists the prefix, follows all listing pages, and selects
`mts/YYYY/MM/manifest.json` objects in sorted key order. Other feed JSON files
are not selected directly. Missing months are skipped; finding no manifests is
an error. An unexpected manifest location also causes an error.

Each month must contain:

```text
mts/YYYY/MM/
  manifest.json
  mts_table_1.json
  ...
  mts_table_9.json
```

The manifest must reference exactly those nine table files. Before writing a
report, the script validates hashes, row counts, report dates, source schemas,
and typed values for all nine files. Each source object, including the manifest,
is limited to 32 MiB.

## Run from the AWS console

1. Open AWS Glue in the account and region containing the lakehouse stack.
2. Open **ETL jobs** and select the job from the `GlueJobName` stack output.
3. In the job's run parameters, add or replace `--base_prefix` with the desired
   value, such as `mts/2026/08`. The deployed default, `REQUIRED`, is a placeholder
   and must be replaced with a valid prefix.
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
'{"--base_prefix":"mts/2026/08"}' | Set-Content -LiteralPath $argumentsPath -Encoding ascii

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

Repeat `get-job-run` to check progress. For a year or full backfill, change the
JSON file's `--base_prefix` value to `mts/2025` or `mts` before starting a new run.

## Job configuration and arguments

With the supplied stack, `--base_prefix` is the only argument you need to supply
at run time. These other required script arguments are configured as
non-overridable job arguments:

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
| Invalid prefix / default `REQUIRED` | Set `--base_prefix` to one of the supported forms above. |
| No MTS manifests found | Check the configured feeds bucket and prefix; run the downloader if feeds are missing. |
| SHA-256, row-count, or report-date mismatch | Check that the month has a complete, consistent feed and manifest; regenerate the complete report if needed. |
| Source schema changed / target schema differs | Review the source schema or explicitly migrate the target schema before retrying. The loader does not alter existing schemas automatically. |
| Access denied | Check the Glue execution role's source-list/read, source-version-read, script-read, S3 Tables, and log permissions against the template. |
| Timeout | Increase `GlueTimeoutMinutes` or run smaller prefixes, then rerun the affected reports. |

For optional Athena verification and its separate catalog integration setup,
see [Query the MTS tables with Athena](../../mts_lakehouse/README-lakehouse_for_mts_data.md#query-the-mts-tables-with-athena).
