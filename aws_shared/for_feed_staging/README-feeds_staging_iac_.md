# Shared feeds staging bucket

`feeds_staging_iac.yaml` creates the `acctguv-feeds-<region>` S3 bucket and
grants read access to an existing IAM developer group.

## Deploy from the AWS console

1. In CloudFormation, create a stack with `feeds_staging_iac.yaml`, or update
   the existing feeds stack with this template.
2. Set `DeveloperGroupName` to an existing IAM group. It defaults to `developer`.
3. Review the change set and acknowledge named IAM resources
   (`CAPABILITY_NAMED_IAM`).
4. After deployment, use the `FeedsBucketName` and `FeedsBucketArn` outputs
   to configure feed producers and consumers.

Update the existing stack when the bucket is already under CloudFormation
management. For an existing unmanaged bucket, use CloudFormation resource import.

## Bucket configuration

- Versioning, S3-managed encryption, blocked public access, disabled ACLs, and HTTPS-only access.
- Eligible current and noncurrent versions transition to Standard-IA after 30 days.
- Noncurrent versions expire after 90 days. Incomplete multipart uploads are aborted after 7 days.
- Developer group members can list the bucket and read current and previous object versions.
- CloudFormation retains the bucket on stack deletion or replacement. Lifecycle rules and storage charges continue. Stack deletion removes the group policy and bucket policy.

The deployment identity or CloudFormation service role needs permissions to
manage the bucket, its policy, and the IAM group policy.
