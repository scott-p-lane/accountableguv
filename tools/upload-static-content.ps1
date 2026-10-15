<#
.SYNOPSIS
Uploads the website's static content to s3://acctguv-static-content/.
.DESCRIPTION
Uses AWS CLI sync to upload new and changed files. The contents of "static
content" go directly into the bucket root; subdirectory names are preserved.
Local files and destination-only S3 objects are not deleted.
Requires AWS CLI and configured AWS credentials with access to the bucket.
.EXAMPLE
.\tools\upload-static-content.ps1 -DryRun
.EXAMPLE
.\tools\upload-static-content.ps1
.EXAMPLE
.\tools\upload-static-content.ps1 -Profile website -Region us-east-1
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Profile,
    [string]$Region
)

$ErrorActionPreference = 'Stop'
$sourceDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'static content'
$destination = 's3://acctguv-static-content/'

if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
    throw "Static content directory not found: $sourceDirectory"
}

$awsCommand = Get-Command aws -CommandType Application -ErrorAction SilentlyContinue
if (-not $awsCommand) {
    throw 'AWS CLI was not found on PATH. Install AWS CLI and configure credentials before running this script.'
}

# Sync the contents, not a "static content" prefix. For example:
# static content/home.html -> s3://acctguv-static-content/home.html
# static content/mts/table-4.html -> s3://acctguv-static-content/mts/table-4.html
$awsArguments = @('s3', 'sync', $sourceDirectory, $destination, '--no-progress')
if ($DryRun) { $awsArguments += '--dryrun' }
if ($Profile) { $awsArguments += @('--profile', $Profile) }
if ($Region) { $awsArguments += @('--region', $Region) }

Write-Host "Source:      $sourceDirectory"
Write-Host "Destination: $destination"
if ($DryRun) { Write-Host 'Preview only; no files will be uploaded.' }

& $awsCommand.Source @awsArguments
if ($LASTEXITCODE -ne 0) {
    throw "AWS CLI upload failed with exit code $LASTEXITCODE."
}
