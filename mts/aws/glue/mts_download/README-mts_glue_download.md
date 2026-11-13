# Bulk Treasury MTS downloads in AWS Glue

The on-demand job saves original Treasury responses and a manifest per report
month. From October 1997 through February 2015 it keeps the original STAR
text under `raw/` and writes nine transformed table JSON files in the month
folder. The manifest points to the table files. From March 2015 onward the
manifest points to the original Fiscal Data API pages. One run can span both
sources.

See the [STAR archive backfill instructions](README-mts_pre_march_2015.md)
for the local Python command.

## Deploy

Run the deployment script from the repository root with Python and the AWS
CLI available. Use the feeds stack's region and an existing code bucket in
that region.

```powershell
./mts/aws/glue/mts_download/deploy_mts_glue_download.ps1 -Region us-east-2 -CodeBucketName 'your-existing-code-bucket' -Version 'v1.2.0-rc1'
```

The default report location is `s3://acctguv-feeds-REGION/mts/`. If your
feeds stack uses a different bucket, pass `-FeedsBucketName BUCKET`. To
authorize a second destination for individual runs, pass
`-AlternateBucketName BUCKET` and optionally `-AlternateReportPrefix PREFIX`
(defaults to `mts`). Pass `-Profile PROFILE` to select an AWS CLI profile.
The script uploads the job script and wheel to `glue/mts_download/v1.2.0-rc1/`
in the code bucket. A version must start with a letter or digit and can also
contain periods, underscores, and hyphens. A version containing only digits
keeps the existing naming convention, so `1` uses `v1/`. Use a new version
when either artifact changes.

The stack creates a Python 3.9 shell job and its execution role.
[AWS Glue Python shell job documentation](https://docs.aws.amazon.com/glue/latest/dg/add-job-python.html)

## Start a run

In AWS Glue Studio, open `MTS-Bulk-mts-download` and choose **Run with
parameters**. Enter values for `--start_year` and `--start_month`. For a
range, also enter `--end_year` and `--end_month`. Leave both end values at
`unset` for one month. Leave `--destination` at `default` to use the feeds
location, or enter the stack's `AlternateDestination` URI.

Use the stack's `DownloadGlueJobName` output. This example downloads February
through March 2015 into the default feeds location.

```powershell
aws glue start-job-run --region us-east-2 --job-name MTS-Bulk-mts-download --arguments='--start_year=2015,--start_month=2,--end_year=2015,--end_month=3'
```

- Supply `--start_year` and `--start_month` on every run. Supply both
  `--end_year` and `--end_month` for an inclusive range. Omit both to
  download only the start month.
- For the alternate location, append `,--destination=s3://BUCKET/PREFIX`
  inside the arguments string. Use the stack's `AlternateDestination` output
  for the exact URI. Reports are written below that prefix as `YYYY/MM/`.
- Select published months. If Treasury has yet to publish a selected
  report or a download fails, the Glue run fails and logs the report date.
  Completed months remain in S3. Rerunning the range skips writes for
  byte-identical objects.

Deploy the [updated lakehouse loader](../mts_load/README-mts_load.md) before
running this downloader against the feeds bucket. Select the desired
`mts`, `mts/YYYY`, or `mts/YYYY/MM` input prefix when loading.

If a run exits with code 2, check the date arguments. Both start values
must be set even when both end values are supplied. For example, set the
start to year `2016`, month `1` and the end to year `2016`, month `12`
to download all of 2016. If Glue Studio shows no logs, look for the run ID
in the CloudWatch log group `/aws-glue/python-jobs/error` in the job's
region. [AWS Glue Python shell logs](https://docs.aws.amazon.com/glue/latest/dg/add-job-python.html)
