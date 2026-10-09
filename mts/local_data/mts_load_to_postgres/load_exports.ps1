[CmdletBinding()]
param(
    [string]$S3Prefix = 's3://acctguv-feeds-us-east-2/exports/mts_exports/',
    [string]$Region = 'us-east-2',
    [string]$Profile,
    [string]$CsvDirectory = (Join-Path $PSScriptRoot '../mts_export'),
    [string]$Database = 'mts',
    [string]$DbUser = 'postgres',
    [string]$DbHost = 'localhost',
    [ValidateRange(1, 65535)][int]$DbPort = 5432,
    [string]$PsqlExecutable = 'psql',
    [string]$AwsExecutable = 'aws'
)
$ErrorActionPreference = 'Stop'

if ($S3Prefix -notmatch '^s3://[^/]+/.+') { throw 'S3Prefix must specify an S3 bucket and folder.' }
$S3Prefix = $S3Prefix.TrimEnd('/') + '/'
$awsCommand = Get-Command $AwsExecutable -ErrorAction Stop
$psqlCommand = Get-Command $PsqlExecutable -ErrorAction SilentlyContinue
if (-not $psqlCommand -and $PsqlExecutable -eq 'psql') {
    $postgresInstall = Join-Path $env:ProgramFiles 'PostgreSQL/18/bin/psql.exe'
    $psqlCommand = Get-Command $postgresInstall -ErrorAction SilentlyContinue
}
if (-not $psqlCommand) { throw 'psql was not found. Add it to PATH or pass -PsqlExecutable with its full path.' }
$loader = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'load_mts_data.sql')).Path
$destination = [System.IO.Path]::GetFullPath($CsvDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$staging = Join-Path $destination ('.download-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null
$awsOptions = @('--region', $Region, '--no-cli-pager')
if ($Profile) { $awsOptions += @('--profile', $Profile) }

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

# Promote only after all nine CSV downloads succeed.
foreach ($table in $expectedTables) {
    $filename = "${table}_export.csv"
    Move-Item -LiteralPath (Join-Path $staging $filename) -Destination (Join-Path $destination $filename) -Force
}
Remove-Item -LiteralPath $staging
Write-Host "All $($expectedTables.Count) CSV downloads saved to $destination"

$csvPath = $destination.Replace('\', '/')
Write-Host "Loading all nine tables into $Database on ${DbHost}:$DbPort from $destination"
$loadLog = Join-Path $destination 'postgres_load.log'
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
Write-Host 'Download and PostgreSQL load completed successfully.'
