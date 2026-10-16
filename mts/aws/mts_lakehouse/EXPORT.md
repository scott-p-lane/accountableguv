# Export MTS CSVs from the lakehouse stack

`mts_lakehouse_iac.yaml` manages ingestion, Athena, and the export job in one
stack. Export has its own role, automatically attached to the stack's Athena
query policy, plus scoped script/output/log permissions. The standalone export
stack has been removed from the repository.

## Enable or update export

Upload the updated script and update the existing lakehouse stack using the
console steps below. Use the same stack rather than creating another lakehouse.

## Console deployment or new lakehouse

1. Upload [`export_mts_csv.py`](../glue/mts_export/export_mts_csv.py) as a plain
   Python file to `GlueScriptBucketName`, for example at
   `glue/mts_export/export_mts_csv.py`. Use SSE-S3 encryption.
2. Update the existing lakehouse stack with `mts_lakehouse_iac.yaml`, or supply
   these export parameters when creating a new lakehouse.
3. Set **ExportScriptObjectKey** to the uploaded key. Keep **GlueScriptObjectKey**
   set to the ingestion script. Keep all other existing parameter values.
4. Keep **ExportPrefix** as `exports/mts_exports/`. Export uses the lakehouse's
   existing feeds bucket.
5. Acknowledge IAM creation and review the change set: enabling export adds a
   job, role, and two log groups without replacing the ingestion/Athena/table
   resources. Run the job named by **ExportGlueJobName** after completion.

Empty `ExportScriptObjectKey` disables export. Clearing it after enabling export
removes its job/role/log groups; CSVs and uploaded scripts remain in S3.

## Output and runtime

For the default feeds bucket in us-east-2:

```text
s3://acctguv-feeds-us-east-2/exports/mts_exports/mts_table_1_export.csv
...
s3://acctguv-feeds-us-east-2/exports/mts_exports/mts_table_9_export.csv
```

CSV filenames are stable: `mts_table_N_export.csv`. Every run replaces the
previous export's files. CSVs
contain headers and match the PostgreSQL loaders directly, without renaming.

Use the CSVs only after the Glue run succeeds and while no new export is running.
The job finishes all nine queries before replacing CSVs. A mid-copy failure can
leave mixed files; rerun to repair them before loading PostgreSQL. Keep
ingestion/source writers idle during export; separate Athena queries do not
provide a cross-table snapshot. A service-level stop may leave a query running.

The Glue 5.0 `glueetl` job uses two G.1X workers, 150-minute timeout, one concurrent
run, and no automatic retries. `ExportQueryTimeoutSeconds` defaults to 900 per
query. Athena produces native CSVs; Glue copies them within S3 to the named export files.
No local export command, extra modules, or Spark part files are involved.
Glue, Athena, S3 copies/storage, and logs incur charges; original results remain.

## Permissions and checks

The stack grants exact script-key access, export-prefix CSV writes, and log
writes. It attaches `MtsAthenaQueryPolicy` internally
for Athena execution/results, Glue catalog visibility, and S3 Tables reads.
No workgroup/catalog/policy ARN needs copying between stacks.

For Lake Formation authorization, an administrator must grant **ExportGlueRoleArn**
catalog/database visibility and SELECT on the nine tables. IAM
`lakeformation:GetDataAccess` is included but does not create those data grants.
Existing explicit denies still apply. Script/results/export buckets assume
SSE-S3; customer-managed KMS keys require additional permissions/key policies.

```powershell
python -m unittest discover -s mts/glue/mts_export/tests -v
cfn-lint mts/mts_lakehouse/mts_lakehouse_iac.yaml
```

After deployment, verify all nine filenames, headers/counts,
and sample dates/decimals/text/NULLs. Automated tests mock AWS clients and do not
verify live IAM, Lake Formation, Glue, or PostgreSQL execution.
