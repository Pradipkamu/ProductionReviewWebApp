param(
    [string]$OracleHost = '92.4.90.35',
    [string]$OracleUser = 'ubuntu',
    [string]$KeyPath = "$HOME\.ssh\ssh-key-2026-10-05.key",
    [string]$RemoteAppPath = '/home/ubuntu/ProductionReviewWebApp',
    [string]$AppPath = 'D:\Machine Shop MIS',
    [string]$DownloadDirectory = 'D:\Machine Shop MIS\database\oracle_backups'
)

$ErrorActionPreference = 'Stop'

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory)][string]$Program,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$InputText
    )
    $exe = (Get-Command $Program -ErrorAction Stop).Source
    $saved = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $LASTEXITCODE = $null
        if ($PSBoundParameters.ContainsKey('InputText')) {
            $nativeOutput = @($InputText | & $exe @Arguments 2>&1)
        } else {
            $nativeOutput = @(& $exe @Arguments 2>&1)
        }
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $saved
    }
    $lines = @($nativeOutput | ForEach-Object { $_.ToString() })
    if ($exitCode -ne 0) {
        $lines | ForEach-Object { Write-Host $_ }
        throw "$Program failed with exit code $exitCode."
    }
    $lines
}

foreach ($program in @('ssh.exe','scp.exe','docker.exe','tar.exe')) {
    if (-not (Get-Command $program -ErrorAction SilentlyContinue)) {
        throw "$program is unavailable."
    }
}
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "SSH private key not found: $KeyPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $AppPath 'docker-compose.yml'))) {
    throw "docker-compose.yml not found in $AppPath"
}

New-Item -ItemType Directory -Force -Path $DownloadDirectory | Out-Null
$sshTarget = "$OracleUser@$OracleHost"

Write-Host "Resolving latest verified Oracle backup set..." -ForegroundColor Cyan
$resolveScript = @'
set -e
APP_PATH="__APP_PATH__"
db=$(find "$APP_PATH/database/backups" -maxdepth 1 -type f -name 'pms_*.dump' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
att=$(find "$APP_PATH/database/backups" -maxdepth 1 -type f -name 'attachments_*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$db" && test -s "$db" && test -s "$db.sha256"
test -n "$att" && test -s "$att" && test -s "$att.sha256"
printf 'DB=%s\nDBSHA=%s\nATT=%s\nATTSHA=%s\n' "$db" "$db.sha256" "$att" "$att.sha256"
'@
$resolveScript = $resolveScript.Replace('__APP_PATH__', $RemoteAppPath)
$remote = @(Invoke-NativeChecked -Program 'ssh.exe' -Arguments @(
    '-T','-i',$KeyPath,$sshTarget,'tr -d ''\r'' | bash -s'
) -InputText $resolveScript)

function Get-Marker([string]$Name) {
    $line = $remote | Where-Object { $_ -like "$Name=*" } | Select-Object -Last 1
    if (-not $line) { return $null }
    (($line -replace "^$Name=", '')).Trim()
}

$remoteDb = Get-Marker 'DB'
$remoteDbSha = Get-Marker 'DBSHA'
$remoteAtt = Get-Marker 'ATT'
$remoteAttSha = Get-Marker 'ATTSHA'
if (-not $remoteDb -or -not $remoteDbSha -or -not $remoteAtt -or -not $remoteAttSha) {
    throw 'Latest verified Oracle database/attachment backup set could not be resolved.'
}

$localDb = Join-Path $DownloadDirectory $remoteDb.Split('/')[-1]
$localDbSha = "$localDb.sha256"
$localAtt = Join-Path $DownloadDirectory $remoteAtt.Split('/')[-1]
$localAttSha = "$localAtt.sha256"

foreach ($pair in @(
    @($remoteDb,$localDb), @($remoteDbSha,$localDbSha),
    @($remoteAtt,$localAtt), @($remoteAttSha,$localAttSha)
)) {
    Write-Host "Downloading $($pair[0].Split('/')[-1]) ..." -ForegroundColor Cyan
    Invoke-NativeChecked -Program 'scp.exe' -Arguments @(
        '-i',$KeyPath,("${sshTarget}:$($pair[0])"),$pair[1]
    ) | Out-Null
}

function Assert-Hash([string]$File,[string]$HashFile) {
    $expected = ((Get-Content -LiteralPath $HashFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw "SHA-256 verification failed: $File" }
}
Assert-Hash $localDb $localDbSha
Assert-Hash $localAtt $localAttSha
Write-Host "Oracle database and attachments downloaded and verified." -ForegroundColor Green

Write-Host ""
Write-Host "WARNING: This will replace the Windows MIS database and attachments." -ForegroundColor Yellow
Write-Host "A rollback backup of the current Windows data will be created first." -ForegroundColor Yellow
if ((Read-Host 'Type RESTORE to continue') -cne 'RESTORE') {
    Write-Host 'Restore cancelled. No Windows data changed.' -ForegroundColor Yellow
    exit 0
}

Set-Location $AppPath
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$rollback = Join-Path $AppPath "database\pre_restore_$stamp"
New-Item -ItemType Directory -Force -Path $rollback | Out-Null

Write-Host "Creating Windows pre-restore rollback backup..." -ForegroundColor Cyan
Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','up','-d','db') | Out-Null
Invoke-NativeChecked -Program 'docker.exe' -Arguments @(
    'compose','exec','-T','db','pg_dump','-U','pms','-d','pms','-Fc','-f','/tmp/windows_pre_restore.dump'
) | Out-Null
Invoke-NativeChecked -Program 'docker.exe' -Arguments @(
    'compose','cp','db:/tmp/windows_pre_restore.dump',(Join-Path $rollback 'pms.dump')
) | Out-Null

$attachmentsDir = Join-Path $AppPath 'database\attachments'
if (Test-Path $attachmentsDir) {
    Copy-Item -LiteralPath $attachmentsDir -Destination (Join-Path $rollback 'attachments') -Recurse -Force
}

Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','stop','backend') | Out-Null

try {
    Write-Host "Restoring Oracle PostgreSQL database..." -ForegroundColor Cyan
    Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','cp',$localDb,'db:/tmp/oracle_restore.dump') | Out-Null
    Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','exec','-T','db','dropdb','-U','pms','--if-exists','pms') | Out-Null
    Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','exec','-T','db','createdb','-U','pms','-O','pms','pms') | Out-Null
    Invoke-NativeChecked -Program 'docker.exe' -Arguments @(
        'compose','exec','-T','db','pg_restore','-U','pms','-d','pms','--no-owner','--no-privileges','/tmp/oracle_restore.dump'
    ) | Out-Null

    Write-Host "Restoring Oracle attachments..." -ForegroundColor Cyan
    $stage = Join-Path $env:TEMP "mis_attachments_$stamp"
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    & tar.exe -xzf $localAtt -C $stage
    if ($LASTEXITCODE -ne 0) { throw 'Attachment archive extraction failed.' }

    if (Test-Path $attachmentsDir) { Remove-Item $attachmentsDir -Recurse -Force }
    $extracted = Join-Path $stage 'attachments'
    if (Test-Path $extracted) {
        Move-Item -LiteralPath $extracted -Destination $attachmentsDir
    } else {
        New-Item -ItemType Directory -Force -Path $attachmentsDir | Out-Null
    }
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "Starting Windows MIS..." -ForegroundColor Cyan
    Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','up','-d','backend','frontend') | Out-Null
    Start-Sleep -Seconds 5
    Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','exec','-T','db','pg_isready','-U','pms','-d','pms') | Out-Null

    Write-Host ""
    Write-Host "Oracle data restored to Windows MIS successfully." -ForegroundColor Green
    Write-Host "Database source:    $localDb"
    Write-Host "Attachments source: $localAtt"
    Write-Host "Rollback backup:    $rollback"
}
catch {
    Write-Host "RESTORE FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Pre-restore rollback backup is preserved at: $rollback" -ForegroundColor Yellow
    try { Invoke-NativeChecked -Program 'docker.exe' -Arguments @('compose','up','-d','backend','frontend') | Out-Null } catch {}
    throw
}
