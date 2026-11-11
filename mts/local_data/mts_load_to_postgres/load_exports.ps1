[CmdletBinding()]
param(
    [string]$S3Prefix,
    [string]$Region = 'us-east-2',
    [string]$Profile,
    [string]$CsvDirectory = (Join-Path $PSScriptRoot '../mts_export'),
    [string]$Database = 'mts',
    [string]$DbUser = 'postgres',
    [string]$DbHost = 'localhost',
    [ValidateRange(1, 65535)][int]$DbPort = 5432,
    [string]$PsqlExecutable = 'psql',
    [string]$AwsExecutable = 'aws',
    [ValidateNotNullOrEmpty()][string]$ExportJobName = 'MTS-Lakehouse-mts-export'
)
$ErrorActionPreference = 'Stop'

$awsCommand = Get-Command $AwsExecutable -ErrorAction Stop
$psqlCommand = Get-Command $PsqlExecutable -ErrorAction SilentlyContinue
if (-not $psqlCommand -and $PsqlExecutable -eq 'psql') {
    $postgresInstall = Join-Path $env:ProgramFiles 'PostgreSQL/18/bin/psql.exe'
    $psqlCommand = Get-Command $postgresInstall -ErrorAction SilentlyContinue
}
if (-not $psqlCommand) { throw 'psql was not found. Add it to PATH or pass -PsqlExecutable with its full path.' }
$loader = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'load_mts_data.sql')).Path
$destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($CsvDirectory)
$awsOptions = @('--region', $Region, '--no-cli-pager')
if ($Profile) { $awsOptions += @('--profile', $Profile) }

$jobResponse = & $awsCommand.Source glue get-job --job-name $ExportJobName --output json @awsOptions
if ($LASTEXITCODE -ne 0) { throw "Could not read Glue job $ExportJobName." }
$job = ($jobResponse | ConvertFrom-Json).Job
$exportLocation = $job.NonOverridableArguments.'--output_s3'
if (-not $exportLocation) { $exportLocation = $job.DefaultArguments.'--output_s3' }
if ($exportLocation -notmatch '^s3://[^/]+/[^/].*') {
    throw "Glue job $ExportJobName must have an S3 export folder configured in --output_s3."
}
$exportLocation = $exportLocation.TrimEnd('/') + '/'
if ($PSBoundParameters.ContainsKey('S3Prefix') -and $S3Prefix.TrimEnd('/') + '/' -cne $exportLocation) {
    throw "S3Prefix must match the Glue job's configured export folder: $exportLocation"
}
$S3Prefix = $exportLocation

Write-Host "Starting Glue export job $ExportJobName in $Region"
$runId = & $awsCommand.Source glue start-job-run --job-name $ExportJobName --query JobRunId --output text @awsOptions
if ($LASTEXITCODE -ne 0 -or -not $runId -or $runId -eq 'None') {
    throw "Could not start Glue export job $ExportJobName."
}
Write-Host "Glue export run: $runId"
$previousState = $null
while ($true) {
    $runResponse = & $awsCommand.Source glue get-job-run --job-name $ExportJobName --run-id $runId --output json @awsOptions
    if ($LASTEXITCODE -ne 0) { throw "Could not check Glue export run $runId." }
    $run = ($runResponse | ConvertFrom-Json).JobRun
    $state = $run.JobRunState
    if ($state -ne $previousState) {
        Write-Host "Glue export run ${runId}: $state"
        $previousState = $state
    }
    if ($state -eq 'SUCCEEDED') { break }
    if ($state -notin @('STARTING', 'RUNNING', 'WAITING', 'STOPPING')) {
        throw "Glue export run $runId ended with status '$state'. $($run.ErrorMessage)"
    }
    Start-Sleep -Seconds 10
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null
$staging = Join-Path $destination ('.download-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null

function Copy-ExportObject([string]$ObjectName, [string]$LocalPath, [int]$FileNumber, [int]$FileCount) {
    Write-Host "[$FileNumber/$FileCount] Downloading $ObjectName"
    Write-Host "  Source:      $($S3Prefix + $ObjectName)"
    Write-Host "  Destination: $(Join-Path $destination $ObjectName)"
    Write-Host "  Temporary:   $LocalPath"
    $downloadTimer = [System.Diagnostics.Stopwatch]::StartNew()
    & $awsCommand.Source s3 cp ($S3Prefix + $ObjectName) $LocalPath @awsOptions
    if ($LASTEXITCODE -ne 0) { throw "Could not download $ObjectName. No database load was started. Staging: $staging" }
    $downloadTimer.Stop()
    $downloadSize = (Get-Item -LiteralPath $LocalPath).Length
    Write-Host ('[{0}/{1}] Download complete: {2:N2} MiB in {3:N1} seconds.' -f $FileNumber, $FileCount, ($downloadSize / 1MB), $downloadTimer.Elapsed.TotalSeconds)
}

Write-Host "Downloading exports from $S3Prefix"
$expectedTables = @(1..9 | ForEach-Object { "mts_table_$_" })
$fileNumber = 0
foreach ($table in $expectedTables) {
    $fileNumber++
    $filename = "${table}_export.csv"
    Copy-ExportObject $filename (Join-Path $staging $filename) $fileNumber $expectedTables.Count
}

# The export job overwrites shared object names. Check that a newer run did
# not start while the files were being downloaded.
$latestRunId = & $awsCommand.Source glue get-job-runs --job-name $ExportJobName --page-size 1 --max-items 1 --query 'JobRuns[0].Id' --output json @awsOptions
if ($LASTEXITCODE -ne 0) { throw "Could not verify the latest Glue export run. Staging: $staging" }
if (($latestRunId | ConvertFrom-Json) -ne $runId) {
    throw "Glue export run $runId is no longer the latest run. No database load was started. Staging: $staging"
}

$csvPath = $staging.Replace('\', '/')
Write-Host "Loading all nine tables into $Database on ${DbHost}:$DbPort"
$loadLog = Join-Path $destination 'postgres_load.log'
Set-Content -LiteralPath $loadLog -Value '' -NoNewline
$savedErrorPreference = $ErrorActionPreference
try {
    # Preserve native stderr in the log instead of replacing it with a generic exception.
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    & $psqlCommand.Source -X -h $DbHost -p $DbPort -U $DbUser -d $Database -v ON_ERROR_STOP=1 -v "csv_dir=$csvPath" -f $loader 2>&1 | Tee-Object -FilePath $loadLog
    $psqlExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedErrorPreference
}
if ($psqlExitCode -ne 0) {
    $details = (Get-Content -LiteralPath $loadLog -Tail 20) -join [Environment]::NewLine
    throw "PostgreSQL load failed (exit $psqlExitCode). Details: $loadLog$([Environment]::NewLine)$details"
}
# Use the run's staged files for psql, then publish the local export copies.
foreach ($table in $expectedTables) {
    $filename = "${table}_export.csv"
    Move-Item -LiteralPath (Join-Path $staging $filename) -Destination (Join-Path $destination $filename) -Force
}
Remove-Item -LiteralPath $staging
Write-Host "Glue export, download to $destination, and PostgreSQL load completed successfully."
