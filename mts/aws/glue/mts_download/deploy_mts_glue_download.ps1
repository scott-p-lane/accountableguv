[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')]
    [string]$CodeBucketName,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Region,

    [ValidatePattern('^[A-Za-z][A-Za-z0-9-]{0,127}$')]
    [string]$StackName = 'MTS-Bulk',

    [ValidatePattern('^([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])?$')]
    [string]$FeedsBucketName = '',

    [ValidatePattern('^([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])?$')]
    [string]$AlternateBucketName = '',

    [ValidatePattern('^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$')]
    [string]$AlternateReportPrefix = 'mts',

    [ValidateRange(1, 2880)]
    [int]$TimeoutMinutes = 180,

    [string]$Profile
)

$ErrorActionPreference = 'Stop'
Get-Command python, aws | Out-Null

$awsOptions = @('--region', $Region, '--no-cli-pager')
if ($Profile) {
    $awsOptions += @('--profile', $Profile)
}

$jobScript = Join-Path $PSScriptRoot 'download_mts_reports.py'
$template = Join-Path $PSScriptRoot 'mts_glue_download_iac.yaml'
$buildDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mts-glue-" + [guid]::NewGuid())
$buildDir = (New-Item -ItemType Directory -Path $buildDir).FullName
try {
    $library = python (Join-Path $PSScriptRoot 'package_glue.py') --output-dir $buildDir
    if ($LASTEXITCODE -ne 0 -or -not $library -or -not (Test-Path -LiteralPath $library -PathType Leaf)) {
        throw 'Could not build the MTS Glue wheel.'
    }

    # Changing either artifact changes the job's S3 code location.
    $scriptHash = (Get-FileHash -LiteralPath $jobScript).Hash.ToLowerInvariant()
    $libraryHash = (Get-FileHash -LiteralPath $library).Hash.ToLowerInvariant()
    $codePrefix = "glue/mts-download/$scriptHash/$libraryHash"
    $codeUri = "s3://$CodeBucketName/$codePrefix"

    aws s3 cp $jobScript "$codeUri/download_mts_reports.py" @awsOptions
    if ($LASTEXITCODE -ne 0) { throw 'Could not upload the Glue job script.' }

    aws s3 cp $library "$codeUri/$(Split-Path -Leaf $library)" @awsOptions
    if ($LASTEXITCODE -ne 0) { throw 'Could not upload the Glue wheel.' }

    $parameters = @(
        "CodeBucketName=$CodeBucketName"
        "CodePrefix=$codePrefix"
        "FeedsBucketName=$FeedsBucketName"
        "AlternateBucketName=$AlternateBucketName"
        "AlternateReportPrefix=$AlternateReportPrefix"
        "TimeoutMinutes=$TimeoutMinutes"
    )
    aws cloudformation deploy --stack-name $StackName --template-file $template --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset --parameter-overrides @parameters @awsOptions
    if ($LASTEXITCODE -ne 0) { throw "CloudFormation deployment failed for $StackName." }
}
finally {
    $buildDirectory = Get-Item -LiteralPath $buildDir
    if ($buildDirectory.FullName -eq $buildDir -and -not ($buildDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
}
