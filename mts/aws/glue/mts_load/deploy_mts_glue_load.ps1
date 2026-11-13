[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')]
    [string]$CodeBucketName,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Region,

    [Parameter(Mandatory)]
    [ValidatePattern('\A[A-Za-z0-9][A-Za-z0-9._-]*\z')]
    [string]$Version,

    [ValidatePattern('^[A-Za-z][A-Za-z0-9-]{0,127}$')]
    [string]$StackName = 'MTS-Lakehouse',

    [string]$Profile
)

$ErrorActionPreference = 'Stop'
Get-Command aws | Out-Null

$awsOptions = @('--region', $Region, '--no-cli-pager')
if ($Profile) {
    $awsOptions += @('--profile', $Profile)
}

$template = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../mts_lakehouse/mts_lakehouse_iac.yaml')).Path
$versionFolder = if ($Version -match '\A[0-9]+\z') { "v$Version" } else { $Version }
$codePrefix = "glue/mts_load/$versionFolder"
$scriptKey = "$codePrefix/mts_to_tables.py"
$transformKey = "$codePrefix/mts_pre_march_2015_transform.py"
$loader = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'mts_to_tables.py')).Path
$transform = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'mts_pre_march_2015_transform.py')).Path

aws s3 cp $loader "s3://$CodeBucketName/$scriptKey" --sse AES256 @awsOptions
if ($LASTEXITCODE -ne 0) { throw 'Could not upload the MTS Glue loader.' }

aws s3 cp $transform "s3://$CodeBucketName/$transformKey" --sse AES256 @awsOptions
if ($LASTEXITCODE -ne 0) { throw 'Could not upload the MTS archive transformer.' }

$parameters = @(
    "GlueScriptBucketName=$CodeBucketName"
    "GlueScriptObjectKey=$scriptKey"
    "ArchiveTransformObjectKey=$transformKey"
)
aws cloudformation deploy --stack-name $StackName --template-file $template --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset --parameter-overrides @parameters @awsOptions
if ($LASTEXITCODE -ne 0) { throw "CloudFormation deployment failed for $StackName." }
