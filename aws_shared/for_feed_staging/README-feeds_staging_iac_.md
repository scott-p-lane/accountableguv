# CloudFormation templates

For the website, use [static_content_cloudfront.yaml](static_content_cloudfront.yaml)
to serve an existing private S3 bucket through CloudFront Origin Access Control.
See the [deployment instructions](static_content_cloudfront.md).

`feeds_staging_iac.yaml` defines the staging bucket and a scheduled Python Lambda
that downloads the latest MTS report as nine JSON tables.
Python logic lives in `../lambda/mts_download/mts_feeds_monthly_download.py`. CloudFormation references
its ZIP in S3; it contains no inline Python. No CDK or bootstrap is required.

## Deploy from the AWS console

1. Run `python package_lambda.py` from `aws_iac/lambda/mts_download`. Upload the
   generated ZIP to an existing S3 bucket in the target region at the printed
   `MtsCodeObjectKey`. In the S3 console, open/create `lambda/` and
   upload the generated `mts_feeds_monthly_download_vYYYYMMDD.zip` file.
   `YYYYMMDD` is the latest packaged source file's last-modified date in the
   packaging machine's local timezone.
2. Open CloudFormation, choose **Create stack** with new resources, then choose
   **Upload a template file** and select `feeds_staging_iac.yaml`.
3. Enter a stack name, such as `accountableguv-feeds`.
4. Set `DeveloperGroupName` to an existing IAM group in this account. It defaults
   to `developer`; the template does not create the group or change membership.
   Supply `MtsCodeBucketName` and `MtsCodeObjectKey` for the uploaded ZIP.
5. Review the configuration, acknowledge creation of IAM resources with custom
   names (CAPABILITY_NAMED_IAM), and submit the stack.
6. Wait for `CREATE_COMPLETE`. The **Outputs** tab provides `FeedsBucketName` and
   `FeedsBucketArn`, along with `MtsDownloadFunctionName` and `MtsDownloadFunctionArn`.

For an already deployed staging bucket, select its existing CloudFormation stack,
choose **Update stack**, replace the current template with this file, and review
the change set. This adds the Lambda, role, log group, and monthly EventBridge rule
without changing the existing bucket name or logical ID. Do not create a second
stack to manage that same bucket. The deployment may require acknowledgement of
IAM resources with custom names because of the existing developer policy.

The default MTS schedule is the 20th of each month at 18:00 UTC. Use
`MtsScheduleExpression` to change it and `MtsScheduleState` to enable/disable it.
See the [Lambda README](../lambda/mts_download/README.md) for manual testing,
retry behavior, JSON structure, and source maintenance.

Your deployment identity or CloudFormation service role needs permission to create
the S3/Lambda/EventBridge/log resources, manage the IAM policies/role, pass the Lambda
role, and read the uploaded code object. The code bucket must already exist; an
already deployed staging bucket can be used, or a separate artifact bucket.

For code changes, rebuild and upload the new ZIP and update `MtsCodeObjectKey`
in the stack. Each code deployment needs a new S3 key. Same-day builds reuse the
same key; overwriting it alone does not trigger a CloudFormation code update.
Keep old ZIPs available for rollback.
Invoke the deployed function from the Lambda console with `{}`. To run the same
Python logic locally, use `python mts_feeds_monthly_download.py` from
`aws_iac/lambda/mts_download`. This writes to the project folder
`test/data/mts/{year}/{month}` without AWS credentials. For an explicit local S3
upload, install the local requirements and use `--bucket BUCKET --profile dev
--region us-east-1`.
See the [Lambda README](../lambda/mts_download/README.md) for complete local setup
and console/CLI invocation examples.

The bucket is named `acctguv-feeds-<region>`, preserving the current staging template.
Creating this stack will fail if that bucket already exists; this template does not adopt or
migrate an existing bucket. Use CloudFormation resource import for a planned migration
instead of attempting to manage the bucket from two stacks.

## Automatically load downloaded MTS reports

After deploying the [lakehouse stack](../../mts/aws/mts_lakehouse/mts_lakehouse_iac.yaml),
copy its `GlueJobName` output. Update this existing feeds stack with the revised
`feeds_staging_iac.yaml` and set **`MtsGlueJobName`** to that value. Keep the other
parameters unchanged. The Glue job must be in the same account and region and
configured to read this feeds bucket. No Lambda ZIP rebuild is needed.

With this parameter set, the monthly rule starts a Standard Step Functions
workflow instead of invoking Lambda directly:

1. Invoke the downloader synchronously and wait for a successful response.
2. Pass its returned `prefix` (for example `mts/2026/08`) as Glue's
   `--base_prefix`. This loads the report month, not the invocation month.
3. Wait for Glue to finish; the workflow succeeds only when Glue succeeds.

A failed download never reaches Glue. Successful downloads with unchanged
objects still run Glue, allowing a rerun to repair a previous partial load.
The workflow retries transient Lambda service errors and retries other task
failures twice with backoff. Lambda's asynchronous retry configuration does not
apply to these synchronous workflow invocations. Glue failures are not retried
automatically; inspect the failed execution and Glue logs, resolve the issue,
and rerun the affected month using the [loader instructions](../../mts/aws/glue/mts_load/README-mts_load.md).
Avoid overlapping workflows or manual loads: the Glue job permits one run.

The `MtsPipelineArn` stack output identifies the workflow. For a manual
end-to-end run, start an execution there with `{}` and inspect its execution
history. Invoking Lambda directly still downloads only. EventBridge retries
delivery failures when starting the workflow; it does not retry a workflow that
has already started and subsequently fails.

Leave `MtsGlueJobName` empty to retain download-only scheduling. This supports
deploying the feeds stack before the lakehouse stack without a circular stack
dependency. Updating the stack does not immediately start a run. Deployment
also requires Step Functions and the additional IAM role/pass-role permissions.
The workflow uses the [AWS Glue synchronous integration](https://docs.aws.amazon.com/step-functions/latest/dg/connect-glue.html).

## Included configuration

- Versioning, S3-managed encryption, blocked public access, disabled ACLs, and HTTPS-only access.
- Current and noncurrent versions transition to Standard-IA after 30 days.
- Superseded versions expire permanently after 90 days; current versions do not expire.
- Incomplete multipart uploads are aborted after 7 days.
- Developer group members can list the bucket and read current/previous versions.
- The bucket is retained on stack deletion or replacement. Lifecycle rules continue
  to apply, and storage charges continue. The stack's group policy and bucket policy
  are removed on stack deletion, so the HTTPS-only policy is no longer enforced by
  this stack after deletion.

These rules apply to every feed prefix. Objects smaller than 128 KB are excluded
from lifecycle transitions by S3's default. Organize feeds with prefixes such as
`mts/2026/08/mts_table_1.json`. The MTS Lambda uses the report date for this prefix.

## Adding more Lambda functions later

Keep this stack and update its template to add Lambda functions and execution roles.
Preserve the `FeedsBucket` logical ID and bucket name so CloudFormation continues
managing the same bucket. Review a change set before updating.

In the same template, use `!Ref FeedsBucket` for a Lambda environment variable and
`!GetAtt FeedsBucket.Arn` / `!Sub '${FeedsBucket.Arn}/*'` for bucket/object IAM resources.
Each Lambda execution role needs its own scoped S3 permissions; developer group
permissions do not transfer to Lambda.

If you later compose this as a nested stack, upload the child template to S3 and
reference its outputs with `!GetAtt FeedsStorage.Outputs.FeedsBucketName` and
`!GetAtt FeedsStorage.Outputs.FeedsBucketArn`, where `FeedsStorage` is the parent
template's nested-stack logical ID. Outputs deliberately have no global exports,
so they do not introduce export-name dependencies. An already deployed standalone
stack is not automatically moved under a parent by uploading the same template;
extending this existing stack directly is the simplest path.

Reference: [CloudFormation S3 bucket resource](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3-bucket.html).
