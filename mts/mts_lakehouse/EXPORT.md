# Export MTS CSVs from the lakehouse stack

`mts_lakehouse_iac.yaml` manages ingestion, Athena, and the export job in one
stack. Export has its own role, automatically attached to the stack's Athena
query policy, plus scoped script/output/log permissions. The standalone export
stack has been removed from the repository.

## Enable export on an existing lakehouse

From the repository root with AWS CLI credentials configured:

```powershell
./aws_iac/cloud-formation-templates/mts_lakehouse/deploy_export.ps1 -LakehouseStackName YOUR-LAKEHOUSE-STACK -Profile YOUR-PROFILE
```

The helper reads the existing `GlueScriptBucketName`, uploads and verifies the
export script under a SHA-256 key, and updates **the same stack** with the combined
template. It changes only `ExportScriptObjectKey`; other existing parameter
values are preserved. It does not run the job. Use the lakehouse's account/region;
the helper defaults to **us-east-2**. Omit `-Profile` to use default credentials.
Your deployment identity needs script-upload, CloudFormation update, IAM
role/policy attachment, Glue, Logs, and `iam:PassRole` permissions.

After completion, use **ExportGlueJobName** in the stack Outputs to find the
job in Glue and click **Run**. No per-run arguments are required.

## Console deployment or new lakehouse

1. Upload [`export_mts_csv.py`](../../glue/mts_export/export_mts_csv.py) as a plain
   Python file to `GlueScriptBucketName`, for example at
   `glue/mts_export/export_mts_csv.py`. Use SSE-S3 encryption.
2. Update the existing lakehouse stack with `mts_lakehouse_iac.yaml`, or supply
   these export parameters when creating a new lakehouse.
3. Set **ExportScriptObjectKey** to the uploaded key. Keep **GlueScriptObjectKey**
   set to the ingestion script. Keep all other existing parameter values.
4. Keep **ExportPrefix** as `exports/mts_exports/` and **ExportTimeZone** as
   `America/New_York`. Export uses the lakehouse's existing feeds bucket.
5. Acknowledge IAM creation and review the change set: enabling export adds a
   job, role, and two log groups without replacing the ingestion/Athena/table
   resources. Run the job named by **ExportGlueJobName** after completion.

Empty `ExportScriptObjectKey` disables export. Clearing it after enabling export
removes its job/role/log groups; CSVs and uploaded scripts remain in S3.

## Output and runtime

For the default feeds bucket in us-east-2:

```text
s3://acctguv-feeds-us-east-2/exports/mts_exports/mts_table_1_2026-10-08.csv
...
s3://acctguv-feeds-us-east-2/exports/mts_exports/mts_table_9_2026-10-08.csv
s3://acctguv-feeds-us-east-2/exports/mts_exports/export_complete_2026-10-08.json
```

The date is captured once at run start in the configured timezone. Same-day
reruns replace that day's files; other dates remain. CSVs contain headers and
match the PostgreSQL DDL's column order. Rename downloaded local copies to
`mts_table_N.csv` for the current loaders.

Use the CSVs only after the Glue run succeeds and the dated completion marker
appears. The job removes the previous marker, finishes all nine queries before
replacing CSVs, and writes a new marker after all copies succeed. A mid-copy
failure can leave mixed files without a marker; rerun to repair them. Keep
ingestion/source writers idle during export; separate Athena queries do not
provide a cross-table snapshot. A service-level stop may leave a query running.

The Glue 5.0 `glueetl` job uses two G.1X workers, 150-minute timeout, one concurrent
run, and no automatic retries. `ExportQueryTimeoutSeconds` defaults to 900 per
query. Athena produces native CSVs; Glue copies them within S3 to dated names.
No local export command, extra modules, or Spark part files are involved.
Glue, Athena, S3 copies/storage, and logs incur charges; original results remain.

## Permissions and checks

The stack grants exact script-key access, export-prefix CSV writes, completion
marker write/delete, and log writes. It attaches `MtsAthenaQueryPolicy` internally
for Athena execution/results, Glue catalog visibility, and S3 Tables reads.
No workgroup/catalog/policy ARN needs copying between stacks.

For Lake Formation authorization, an administrator must grant **ExportGlueRoleArn**
catalog/database visibility and SELECT on the nine tables. IAM
`lakeformation:GetDataAccess` is included but does not create those data grants.
Existing explicit denies still apply. Script/results/export buckets assume
SSE-S3; customer-managed KMS keys require additional permissions/key policies.

```powershell
python -m unittest discover -s aws_iac/glue/mts_export/tests -v
cfn-lint aws_iac/cloud-formation-templates/mts_lakehouse/mts_lakehouse_iac.yaml
```

After deployment, verify all nine filenames, completion marker, headers/counts,
and sample dates/decimals/text/NULLs. Automated tests mock AWS clients and do not
verify live IAM, Lake Formation, Glue, or PostgreSQL execution.
