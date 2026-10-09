# MTS lakehouse stack

`mts_lakehouse_iac.yaml` creates a new S3 table bucket, `silver_mts` namespace,
Glue 5.0 Spark job, scoped execution role, CloudWatch log groups with 30-day
retention, an Athena SQL workgroup, and a private S3 bucket for query results.
It also creates an optional Glue CSV export job and dedicated execution role
when `ExportScriptObjectKey` is supplied. See the [export setup](EXPORT.md).
It reads the existing feeds bucket without importing or modifying it.
The job creates `mts_table_1` through `mts_table_9` on its first successful load.

This is the manually invoked ingestion foundation. It does not create a schedule,
Step Functions workflow, ingestion ledger, publication-control table, or
account-wide Glue Data Catalog/Lake Formation integration.

## Deploy from the AWS console

1. Use the same account and region as your existing feeds bucket, in a region
   supporting S3 Tables and Glue 5.0.
2. Upload [`mts_to_tables.py`](../../glue/mts_load/mts_to_tables.py) as a **plain
   Python file**, not a ZIP, to an existing same-region S3 bucket. The feeds bucket
   can also hold the script under a separate `glue/` prefix. Use SSE-S3 encryption;
   customer-managed KMS keys require additional key-policy and IAM permissions.
3. Use an immutable script key, for example
   `glue/mts-load/<sha256>/mts_to_tables.py`. From the repository root, obtain the
   checksum with:

   ```powershell
   (Get-FileHash -Algorithm SHA256 -LiteralPath 'aws_iac/glue/mts_load/mts_to_tables.py').Hash.ToLowerInvariant()
   ```

4. Create a **new** CloudFormation stack, such as `accountableguv-mts-lakehouse`,
   and upload `mts_lakehouse_iac.yaml`.
5. Supply these parameters:

   | Parameter | Value |
   | --- | --- |
   | `FeedsBucketName` | Leave empty for `acctguv-feeds-<region>`, or enter the existing bucket name. |
   | `TableBucketName` | Defaults to `acctguv-mts`; must be a new table bucket in this account/region. Use environment-specific names when needed. |
   | `MtsNamespace` | Defaults to `silver_mts`. |
   | `GlueScriptBucketName` | Bucket containing the uploaded Python file. |
   | `GlueScriptObjectKey` | Exact uploaded script key, without `s3://` or bucket name. |
   | `WorkerCount` | Defaults to two G.1X workers. |
   | `GlueTimeoutMinutes` | Defaults to 30; increase for long backfills (maximum 1,440). |
   | `AthenaQueryScanLimitBytes` | Defaults to 1,073,741,824 bytes (1 GiB) scanned per query. |
   | `ExportScriptObjectKey` | Uploaded `export_mts_csv.py` key in `GlueScriptBucketName`. Empty disables export; set it to create the export job and role. |
   | `ExportPrefix` | Defaults to `exports/mts_exports/` in the existing feeds bucket. |
   | `ExportTimeZone` | Defaults to `America/New_York` for dated export filenames. |
   | `ExportQueryTimeoutSeconds` | Defaults to 900 seconds per Athena export query. |

6. Acknowledge IAM resource creation (`CAPABILITY_IAM`), review the change set,
   and create the stack. The deployment identity/service role needs S3 Tables,
   Glue, Athena workgroup, S3 bucket/policy, IAM role/managed-policy, `iam:PassRole`,
   and CloudWatch Logs provisioning permissions.
7. After `CREATE_COMPLETE`, use the `GlueJobName` output to find the job.

CloudFormation does not upload the Python script or load data during deployment.
For code changes, upload to a new immutable key and update `GlueScriptObjectKey`.
Keep prior script objects for rollback. No external JAR download is needed: the
job uses Glue 5.0's bundled Iceberg runtime.

### Update an existing lakehouse stack

Choose **Update stack**, replace its template with this version, and keep the
existing parameter values. Review the change set: it should add the Athena
workgroup, results bucket and bucket policy, and query-access managed policy.
The existing table bucket, namespace, and Glue job do not need replacement.
Do not create a second stack to manage an existing table bucket.

The new scan-limit parameter has a default, so existing deployments do not need
another uploaded Glue script or a new ingestion run just to add Athena.

To add CSV exports to this same stack, upload the export script to the configured
`GlueScriptBucketName` and set `ExportScriptObjectKey`, or run
[`deploy_export.ps1`](deploy_export.ps1). Keep the ingestion script key and other
existing parameter values. The update adds the export job, role, and log groups
without replacing the table bucket, namespace, ingestion job, or Athena resources.
See [export deployment and operation](EXPORT.md). Leaving the new key empty
keeps existing deployments working without an export-script upload.

## Load a report or a range of feeds

Supply `--base_prefix` to recursively discover all `manifest.json` objects under
a source location in the configured feeds bucket:

| Job parameter | Reports selected |
| --- | --- |
| `--base_prefix = mts/2025` | All available months in 2025. |
| `--base_prefix = mts` | All available months across all years. |
| `--base_prefix = mts/2025/01` | January 2025 only. |

A trailing slash is optional. Use a bucket-relative prefix, not an `s3://` URI.
The job follows every S3 listing page without a delimiter, selects manifests,
and processes them in chronological key order using one Spark session. Other
JSON files are ignored. No manifests found is an error. Manifests outside the
expected `mts/YYYY/MM/manifest.json` layout fail validation rather than being
silently skipped. Only existing months are loaded; gaps are not downloaded.

```powershell
aws glue start-job-run --job-name accountableguv-mts-lakehouse-mts-load --arguments '{"--base_prefix":"mts/2025"}' --region us-east-1
```

For prefix loading, update the existing stack with this template to grant the
Glue role `s3:ListBucket` limited to `mts/*`, upload the revised script to a new
immutable key, and update `GlueScriptObjectKey`. Set `GlueTimeoutMinutes` high
enough for your backfill. The table bucket and existing tables stay in place.

`--base_prefix` is required and is the only feed-selection parameter. The
stack's `REQUIRED` placeholder fails until replaced with a valid prefix. For a
single month, use a prefix such as `mts/2026/08`. Remove the old
`--manifest_key` and `--manifest_version_id` arguments from saved run commands
or overrides when updating. Manifest key/version columns remain in the tables
as source lineage; they are not job parameters.

Only one run can execute at a time. There are no automatic retries. The timeout
defaults to 30 minutes and is configurable through `GlueTimeoutMinutes`. Each
report is validated and written before reading the next, keeping driver memory
bounded to one month's payloads. Discovery selects current manifest keys at the
start, not a version-pinned snapshot of the entire source tree.

On failure the job logs the failing manifest and stops. Earlier completed months
remain loaded, and the failing month may be partially written. Rerun the same
prefix or the failing month's prefix after resolving the error: per-period replacement
prevents duplicates. Historical schema changes still require explicit schema
review; prefix loading does not relax the existing source validation.

## Loading and correction behavior

- Read the manifest and require exactly nine table keys within its report-month
  prefix. Validate byte-level SHA-256 hashes, row counts, report dates, every row's
  columns, metadata types, and value conversions before writing table data.
- Read each object once and transform those verified bytes. Capture S3 version
  IDs in lineage; honor an optional `version_id` on manifest file entries.
  The current downloader supplies hashes but not version IDs. If a correction
  changes a referenced object, validation fails; retry with the complete current
  manifest. An old manifest alone cannot guarantee replay after source replacement.
- Use explicit schemas based on the local August 2026 feed. Convert currency to
  `decimal(38,2)` without rounding, dates to `date`, fiscal/calendar components to
  integers, and Treasury's literal `"null"` values to SQL NULL. String identifiers
  retain leading zeros. Preserve source amounts without scaling or aggregation.
- Add source bucket/key/version/hash/URL, manifest key/version, manifest-hash
  `batch_id`, transformation version, and UTC ingestion time to each row.
- Create missing tables with Iceberg format v2 and an identity partition on
  `record_date`. Validate all target schemas before starting replacements.
- Atomically replace only that report date in each table. A rerun replaces the
  same rows without duplicates; corrections also remove rows absent from the
  revised source. Other report dates are preserved. Reruns create new snapshots
  and ingestion timestamps, even when the source content has not changed.

**There is no transaction across all nine tables.** A mid-run failure can leave a
mix of report revisions. Wait for the entire job to succeed before consuming the
report, and rerun the same complete manifest to repair a partial load. Do not run
other writers against these tables while this job runs. A future publication
layer is needed for consistent reads during ingestion.

Source objects are bounded to 32 MiB each and prepared in driver memory; this is
intended for the current small monthly MTS reports. Revisit the reader for large
feeds. Unexpected source or target schema changes fail rather than automatically
altering tables.

## Verify a deployment

1. Run one available manifest and confirm the job succeeds. Logs include the
   batch ID, report date, and checked target row count for each of nine tables.
2. Confirm all nine tables exist in the table bucket's namespace.
3. Rerun the same manifest and confirm row counts remain unchanged.
4. Load a second report date and confirm the first period remains available.
5. In a non-production bucket, test a corrected report with a removed row and
   confirm its period is replaced rather than appended.

## Query the MTS tables with Athena

The workgroup is named `<TableBucketName>-queries` (`acctguv-mts-queries` by
default). It uses Athena SQL engine version 3 and enforces encrypted output to
`s3://<generated-results-bucket>/queries/`, even if a client specifies another
result location. The bucket blocks public access, disables ACLs, requires HTTPS,
and uses SSE-S3 encryption. The expected bucket owner is the current AWS account.
Completed result files do not automatically expire; incomplete multipart uploads
are aborted after seven days.

A workgroup configures query execution; result files are stored in the regular
S3 results bucket, separately from the Iceberg tables in the S3 table bucket.
These result files are not automatically loaded back into the lakehouse.

Before the first table query:

1. Enable **S3 Tables integration with AWS analytics services / Glue Data Catalog**
   in this account and region if it is not already enabled. Follow the
   [AWS integration instructions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-aws.html).
   This is shared account/region configuration, so this stack does not create or
   take ownership of it. The Glue loader's direct REST connection does not enable
   this integration automatically.
2. Attach the policy from the `AthenaQueryPolicyArn` output to your querying IAM
   user, group, or role. For IAM Identity Center, add it through the appropriate
   permission set. It grants query execution in this workgroup, read/write access
   to its result prefix, and read access to the MTS catalog and namespace. It
   grants no writes to the MTS tables. The stack attaches it to the export role
   when exports are enabled; analyst identities need their own attachment.
   Existing permissions and explicit denies still apply.
3. If this catalog uses **Lake Formation** authorization, an administrator must
   also grant the querying principal the appropriate catalog/database visibility
   and table `SELECT` permissions, plus IAM `lakeformation:GetDataAccess`.
   The supplied policy covers IAM-based catalog access, not Lake Formation grants.
4. After a successful Glue load, open Athena in the same region. Select the
   `AthenaWorkGroupName` output, data source **AwsDataCatalog**, the
   `AthenaTableCatalog` output, and the `Namespace` output.
5. Run a read-only check:

   ```sql
   SELECT record_date, COUNT(*) AS row_count
   FROM mts_table_1
   GROUP BY record_date
   ORDER BY record_date;
   ```

Confirm the query succeeds and its result file appears at `AthenaResultsLocation`.
The query identity supplies permissions; this SQL workgroup does not use the Glue
job's execution role. Principals with S3 read access to the results can read those
files directly, so treat result access as access to the returned data. Members of
this workgroup with the supplied policy share access to its query results.

CloudWatch query metrics are enabled. The scan cutoff defaults to 1 GiB per query
and can be changed with `AthenaQueryScanLimitBytes` (10 MB through 2,147,483,647
bytes, within the CloudFormation property's integer range). Athena cancels queries
that exceed the cutoff; scanned data is still billable. This is not a monthly
budget or a precise cap on the bytes billed.

## Retention and costs

The table bucket, namespace, Athena workgroup, results bucket, and results bucket
policy are retained on stack deletion/replacement; the job-created tables remain
with their bucket. Changing names creates new empty resources,
not a data migration. Retained resources continue to incur storage/maintenance
charges and require deliberate manual cleanup. The job, Glue role, and log groups
are deleted with the stack. The query managed policy is also stack-owned: detach
any manually added policy attachments before deleting the stack. Retaining the
results/workgroup does not retain that policy's access grants. S3 Tables' default
maintenance settings apply.

Historical Iceberg snapshots are not permanent revision archives. Also, the
existing feeds stack expires noncurrent source versions after 90 days. This
stack changes neither policy. Agree on archival retention before relying on old
source versions or snapshots for long-term audit/replay.

Compute runs only on invocation, with a default of two G.1X workers. Storage,
S3 Tables maintenance, source reads (including Standard-IA retrieval where
applicable), logs, Glue execution, Athena queries, and result storage/requests are
additional charges. The results bucket has no automatic expiration policy.

## Local checks

From the repository root:

```powershell
python -m unittest discover -s aws_iac/glue/mts_load/tests -v
cfn-lint aws_iac/cloud-formation-templates/mts_lakehouse/mts_lakehouse_iac.yaml
```

The tests use the Python standard library and mock the Spark write boundary.
They do not validate live IAM permissions or an actual Glue/Iceberg execution;
the deployment smoke tests above are still required.

References:

- [Glue jobs with S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-glue.html)
- [S3 Tables REST endpoint and limitations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html)
- [CloudFormation table bucket](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3tables-tablebucket.html)
- [S3 Tables permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3tables.html)
- [Athena workgroup configuration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-athena-workgroup.html)
- [Query S3 Tables with Athena](https://docs.aws.amazon.com/athena/latest/ug/gdc-register-s3-table-bucket-cat.html)
