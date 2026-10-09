# Private S3 website through CloudFront

Deploy `static_content_cloudfront.yaml` to serve your existing static-content
bucket through a public CloudFront HTTPS URL. The bucket remains private.
Origin Access Control (OAC) signs all origin requests using SigV4, and the
bucket policy grants `s3:GetObject` only to this distribution's CloudFront
service principal. Viewer HTTP requests redirect to HTTPS.

## Deploy through the AWS console

1. In the existing S3 bucket, keep all four **Block Public Access** settings on.
   Use **Bucket owner enforced** Object Ownership (ACLs disabled).
2. Check the bucket's existing policy before deployment. This template manages
   the entire bucket policy and replaces any existing policy. Preserve any
   required statements in this template first. If another stack manages the
   policy, integrate these resources into that stack instead of managing the
   same policy from two stacks.
3. Open CloudFormation in the **same AWS account and region as the bucket**.
   Create a stack and upload `static_content_cloudfront.yaml`.
4. Set `StaticContentBucketName` to the actual S3 bucket name. "static content"
   is a descriptive label or local directory; S3 bucket names cannot contain
   spaces. The template uses the existing bucket and does not create one.
5. Leave `DefaultRootObject` as `home.html` for this repository. Upload the
   **contents** of the local `static content` directory to the bucket root,
   preserving subdirectories, so `home.html` is at the root.
6. Create the stack and wait for `CREATE_COMPLETE`. Open `WebsiteUrl` from
   **Outputs**. No custom domain, ACM certificate, or IAM resource creation
   acknowledgement is required. The deployment identity needs permission to
   manage CloudFront distributions, OACs, cache policies, and the S3 bucket policy.

The stack does not change the existing bucket's public-access or ownership
settings; configure them in step 1. It uses the regional S3 REST endpoint.
S3 website hosting is unnecessary; website endpoints do not support OAC.
The default root object applies to `/`; directory index rewriting and SPA
fallback routing are not configured.

Objects encrypted with SSE-S3 work without additional key permissions. For
SSE-KMS objects, also grant `kms:Decrypt` in the customer-managed KMS key policy
to `cloudfront.amazonaws.com`, restricted by `AWS:SourceArn` to the
`DistributionArn` output. This template does not manage existing KMS keys.

## Verify and update content

- Confirm `WebsiteUrl` and a known asset return the expected content.
- Confirm an unsigned S3 URL for the same object returns AccessDenied.
- Confirm the bucket still has all four Block Public Access settings enabled.

CloudFront caches objects for one hour by default and honors object
`Cache-Control` headers from zero to one year. Query strings and cookies do
not vary the cache. Use versioned asset filenames, short cache headers for HTML,
or a CloudFront invalidation after replacing files that need immediate updates.

Deleting the stack removes its distribution and bucket policy; it does not
delete the existing bucket or its objects. Any former bucket policy is not
automatically restored. Bucket Block Public Access settings remain unchanged.

Reference: [AWS guidance on private S3 origins and OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html).
