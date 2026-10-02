# Monthly Treasury Statement JSON download

`mts_feeds_monthly_download.py` downloads all nine MTS tables from Treasury's Fiscal Data API.
It discovers the latest `record_date` from Table 1, then filters every table to that
date and follows pagination until all rows have been collected. Dates use the
calendar report period, never the download date or fiscal year.

For an August 2026 report downloaded in September, the staging bucket receives:

```text
mts/2026/08/mts_table_1.json
...
mts/2026/08/mts_table_9.json
mts/2026/08/manifest.json
```

S3 keys have no leading `/`; the logical prefix is `mts/{year}/{month}/`, with a
four-digit year and two-digit month. Each table JSON includes `report_date`,
`source_url`, all API `data` rows, and `meta` with labels, types, formats, and row
count. Monetary values remain Treasury's original strings to preserve precision.
The manifest lists all table keys, row counts, and SHA-256 hashes.

All tables are validated before uploading. The manifest is written last; consumers
should verify its hashes before processing, since multiple S3 objects are not an
atomic transaction. Repeat runs skip matching objects. Corrections replace the
same keys, producing new versions under the bucket's existing versioning policy.

The function expects the previous calendar month's report. An absent or stale
release raises an error rather than silently storing an older month's data. This
also means a manual invocation early in a month can fail before the new report is
published. Scheduled runs do not backfill historical gaps; local runs can request
an explicit date range as described below.

## Deployment and schedule

The template `../../cloud-formation-templates/feeds_staging_iac.yaml` references
a ZIP deployment package in S3. It creates an execution role limited to `mts/*`
in the existing staging bucket, logs retained for 30 days, and an EventBridge monthly schedule.
Update the **existing** staging stack using that template. Its bucket name and
`FeedsBucket` logical ID have been preserved.

From this directory, build the package (Python standard library only):

```powershell
python package_lambda.py
```

This prints the ZIP path and `MtsCodeObjectKey`, such as
`lambda/mts_feeds_monthly_download_vYYYYMMDD.zip`. The ZIP contains only `mts_feeds_monthly_download.py` at its root.
The version is the latest filesystem last-modified date among the packaged source
files, formatted as `YYYYMMDD` in the packaging machine's local timezone. It is
not the build date or Git commit date.
Upload it to an **existing** S3 bucket in the Lambda's region. In the S3 console,
create/open the `lambda/` folder and upload the generated `mts_feeds_monthly_download_vYYYYMMDD.zip`.
You can use a deployment-artifact bucket, or the already-created staging bucket.
For a new stack, the code bucket must already exist before creating the stack.

Optional AWS CLI upload:

```powershell
aws s3 cp ./build/mts_feeds_monthly_download_vYYYYMMDD.zip s3://YOUR_CODE_BUCKET/lambda/mts_feeds_monthly_download_vYYYYMMDD.zip --profile dev --region us-east-1
```

When updating the existing stack in the CloudFormation console, upload
`feeds_staging_iac.yaml` and supply:

- `MtsCodeBucketName`: the bucket where you uploaded the ZIP.
- `MtsCodeObjectKey`: the full key printed by the packaging helper.

The deployment identity/CloudFormation service role must be able to read the code
object. For SSE-KMS-encrypted artifacts it also needs decrypt permission on that key.
The function's runtime role does not need access to the code bucket.
Review the change set and acknowledge IAM resource creation before submitting.

Default schedule: 18:00 UTC on the 20th of each month
(`cron(0 18 20 * ? *)`). Treasury normally publishes on the eighth business day of
the following month, so the 20th provides time for normal publication. Change
`MtsScheduleExpression` or set `MtsScheduleState=DISABLED` during the stack update.
There is no immediate download on stack deployment. To test, invoke the function
identified by `MtsDownloadFunctionName` in the Lambda console with the event `{}`.

Transient HTTP failures are retried three times. EventBridge retries delivery
failures, and Lambda retries asynchronous function errors twice within six hours.
Errors are available in CloudWatch Logs and the Lambda Errors metric. A release
delayed beyond those retries requires a later manual invocation; the schedule
does not automatically retry on following days.

The Python 3.13 Lambda runtime provides Boto3, so the deployment ZIP needs no extra
dependencies. The Lambda uses its execution role, not personal login credentials,
and runs outside a VPC to access Treasury's public HTTPS endpoints.

## Run locally without CloudFormation or Lambda

Local runs default to saving JSON files in the repository's `test/data/mts/YYYY/MM`
directory. They require Python and internet access, but no AWS credentials or Boto3.
From the repository root, run:

```powershell
python aws_iac/lambda/mts_download/mts_feeds_monthly_download.py
```

For a December 2025 report, the files are written to `test/data/mts/2025/12`,
regardless of the current working directory. That folder contains nine table JSON
files and `manifest.json`. Identical files are left unchanged. Downloaded test data
is ignored by Git.

To use a different local data root (the script appends `mts/YYYY/MM`):

```powershell
python aws_iac/lambda/mts_download/mts_feeds_monthly_download.py --output-dir ./other-data
```

To download a range of monthly reports, supply both inclusive date bounds:

```powershell
python aws_iac/lambda/mts_download/mts_feeds_monthly_download.py --start-date 2025-01-01 --end-date 2025-12-31
```

Dates use `YYYY-MM-DD` and refer to the report's month-end date, not its publication
date. This example downloads January through December 2025. An end date of
`2025-12-30` excludes December. Equal bounds select a single report when that date
is a month end. Reversed ranges and ranges containing no month end are rejected.
These options also work with `--output-dir` or `--bucket` (and AWS profile/region).
Without either date option, the existing latest-report behavior applies.

Reports are processed oldest first, with nine tables and a manifest per month.
Range success prints a JSON list of per-report results. A missing report or failed
download stops the run with a nonzero exit code; already completed months remain
saved. Rerunning the same range skips identical files or S3 objects.

To explicitly upload to S3 from your computer, create/activate an environment and
install Boto3 from the source directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
aws sso login --profile dev
python mts_feeds_monthly_download.py --bucket acctguv-feeds-us-east-1 --profile dev --region us-east-1
```

For macOS/Linux, activate with `source .venv/bin/activate`. The SSO login step is
only needed for SSO profiles. You may omit `--profile` to use Boto3's normal AWS
credential chain, including temporary credentials supplied through environment
variables. Never put access keys into this source file or command arguments.
`--bucket` must be explicit for local S3 uploads. `STAGING_BUCKET_NAME` is used only
by the deployed Lambda, so it cannot redirect a default local run into AWS.

The `--bucket` mode downloads the same nine tables and writes to the supplied existing
S3 bucket; it does not create infrastructure or schedules. The local identity needs
`s3:ListBucket` limited to `mts/*`, plus `s3:GetObject` and `s3:PutObject` on
`arn:aws:s3:::BUCKET/mts/*`. The developer read-only policy does not grant uploads.
Failures return a nonzero exit code; success prints the report date and prefix.
Use `python mts_feeds_monthly_download.py --help` to see options.

For a deployed Lambda, the console **Test** tab accepts `{}`. CLI invocation:

```powershell
aws lambda invoke --function-name YOUR_FUNCTION_NAME --payload '{}' --cli-binary-format raw-in-base64-out --profile dev --region us-east-1 response.json
Get-Content response.json
```

Use the stack's `MtsDownloadFunctionName` output. A synchronous invocation reports
function failures via `FunctionError` and the response JSON; check those as well as
the command's exit code. CloudWatch Logs contains details.

## Source changes and validation

After editing `mts_feeds_monthly_download.py`, rerun `package_lambda.py`, upload
the resulting ZIP, and update `MtsCodeObjectKey` in the existing stack.
Each code deployment needs a new S3 key. Same-day builds reuse the same key;
overwriting it alone does not trigger a CloudFormation code update.
Keep previously deployed ZIPs available for stack rollback.

Run unit tests from this directory:

```powershell
python -m unittest discover -s tests -v
```

`python probe_treasury.py` performs a read-only live check of all nine report tables;
it does not call AWS or write S3 objects. Packaging tests verify the ZIP source,
handler configuration, and repeatable object key.

Sources: [Treasury API](https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_1?sort=-record_date&page%5Bsize%5D=1),
[Treasury release timing](https://home.treasury.gov/policy-issues/financial-markets-financial-institutions-and-fiscal-service/cash-and-debt-forecasting).
