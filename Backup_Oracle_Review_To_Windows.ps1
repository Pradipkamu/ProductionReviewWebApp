param(
    [string]$OracleHost = '92.4.90.35',
    [string]$OracleUser = 'ubuntu',
    [string]$KeyPath = "$HOME\.ssh\ssh-key-2026-10-05.key",
    [string]$RemoteAppPath = '/home/ubuntu/ProductionReviewWebApp',
    [string]$LocalBackupDirectory = 'D:\Machine Shop MIS\database\oracle_backups'
)

$ErrorActionPreference = 'Stop'

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory)] [string]$Program,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [string]$InputText
    )

    # Windows PowerShell 5.1 turns redirected native stderr into ErrorRecords.
    # Docker progress on stderr is normal; the native exit code decides success.
    $resolvedProgram = (Get-Command $Program -ErrorAction Stop).Source
    $savedPreference = $ErrorActionPreference
    $nativeExitCode = $null
    try {
        $ErrorActionPreference = 'Continue'
        $PSNativeCommandUseErrorActionPreference = $false
        $LASTEXITCODE = $null
        if ($PSBoundParameters.ContainsKey('InputText')) {
            $nativeOutput = @($InputText | & $resolvedProgram @Arguments 2>&1)
        } else {
            $nativeOutput = @(& $resolvedProgram @Arguments 2>&1)
        }
        # Capture immediately after the native command. Some Windows PowerShell 5.1
        # pipelines can leave LASTEXITCODE unset even when the process completed.
        $nativeExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    $outputLines = @($nativeOutput | ForEach-Object { $_.ToString() })
    if ($nativeExitCode -ne 0) {
        $outputLines | ForEach-Object { Write-Host $_ }
        throw "$Program failed with exit code $nativeExitCode. No backup success is assumed."
    }
    $outputLines
}

if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "SSH private key not found: $KeyPath"
}

foreach ($program in @('ssh.exe', 'scp.exe')) {
    if (-not (Get-Command $program -ErrorAction SilentlyContinue)) {
        throw "$program is unavailable. Install the Windows OpenSSH Client feature."
    }
}

New-Item -ItemType Directory -Force -Path $LocalBackupDirectory | Out-Null

Write-Host "Creating verified database backup on $OracleHost ..." -ForegroundColor Cyan

$remoteScript = @'
set -e
APP_PATH="__APP_PATH__"
cd "$APP_PATH"
chmod +x backup_database_linux.sh
sudo ./backup_database_linux.sh
'@

$remoteScript = $remoteScript.Replace('__APP_PATH__', $RemoteAppPath)
$sshTarget = "$OracleUser@$OracleHost"
$remoteOutput = @(Invoke-NativeChecked -Program 'ssh.exe' -Arguments @(
    '-T', '-i', $KeyPath, $sshTarget, 'tr -d ''\r'' | bash -s'
) -InputText $remoteScript)
$remoteOutput | ForEach-Object { Write-Host $_ }

# Resolve the newest verified backup in a separate, machine-readable SSH call.
# This avoids mixing Docker/sudo progress text with the path markers.
$resolveCommand = @'
set -e
APP_PATH="__APP_PATH__"
latest=$(find "$APP_PATH/database/backups" -maxdepth 1 -type f -name 'pms_*.dump' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$latest"
test -s "$latest"
checksum="${latest}.sha256"
test -s "$checksum"
printf '%s\n%s\n' "$latest" "$checksum"
'@
$resolveCommand = $resolveCommand.Replace('__APP_PATH__', $RemoteAppPath)
$pathOutput = @(Invoke-NativeChecked -Program 'ssh.exe' -Arguments @(
    '-T', '-i', $KeyPath, $sshTarget, 'tr -d ''\r'' | bash -s'
) -InputText $resolveCommand | Where-Object { $_ -match '^/.+pms_[0-9T]+Z\.dump(?:\.sha256)?$' })

$remoteBackup = $pathOutput | Where-Object { $_ -match '\.dump$' } | Select-Object -Last 1
$remoteChecksum = $pathOutput | Where-Object { $_ -match '\.dump\.sha256$' } | Select-Object -Last 1
if (-not $remoteBackup -or -not $remoteChecksum) {
    throw 'The Oracle backup was created, but its verified remote paths could not be resolved.'
}
$remoteBackup = $remoteBackup.Trim()
$remoteChecksum = $remoteChecksum.Trim()
$backupName = $remoteBackup.Split('/')[-1]
$checksumName = $remoteChecksum.Split('/')[-1]
$localBackup = Join-Path $LocalBackupDirectory $backupName
$localChecksum = Join-Path $LocalBackupDirectory $checksumName

Write-Host "Downloading $backupName ..." -ForegroundColor Cyan
Invoke-NativeChecked -Program 'scp.exe' -Arguments @(
    '-i', $KeyPath,
    ("{0}:{1}" -f $sshTarget, $remoteBackup),
    $localBackup
)

Invoke-NativeChecked -Program 'scp.exe' -Arguments @(
    '-i', $KeyPath,
    ("{0}:{1}" -f $sshTarget, $remoteChecksum),
    $localChecksum
)

if ((Get-Item -LiteralPath $localBackup).Length -eq 0) {
    throw "Downloaded backup is empty: $localBackup"
}

$expectedHash = ((Get-Content -LiteralPath $localChecksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actualHash = (Get-FileHash -LiteralPath $localBackup -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedHash -ne $actualHash) {
    throw "SHA-256 verification failed for $localBackup"
}

Write-Host ''
Write-Host 'Database backup downloaded and verified successfully.' -ForegroundColor Green
Write-Host "Database: $localBackup"
Write-Host "DB checksum: $localChecksum"
Write-Host "DB SHA-256: $actualHash"

Write-Host ''
Write-Host "Creating verified attachments archive on $OracleHost ..." -ForegroundColor Cyan
$attachmentScript = @'
set -euo pipefail
APP_PATH="__APP_PATH__"
cd "$APP_PATH"
mkdir -p database/backups database/attachments
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$APP_PATH/database/backups/attachments_${stamp}.tar.gz"
checksum="${archive}.sha256"
sudo tar -C "$APP_PATH/database" -czf "$archive" attachments
sudo chown "$(id -u):$(id -g)" "$archive"
test -s "$archive"
sha256sum "$archive" | awk '{print $1}' > "$checksum"
test -s "$checksum"
printf 'ATTACHMENT_ARCHIVE=%s\nATTACHMENT_CHECKSUM=%s\n' "$archive" "$checksum"
'@
$attachmentScript = $attachmentScript.Replace('__APP_PATH__', $RemoteAppPath)
$attachmentOutput = @(Invoke-NativeChecked -Program 'ssh.exe' -Arguments @(
    '-T', '-i', $KeyPath, $sshTarget, 'tr -d ''\r'' | bash -s'
) -InputText $attachmentScript)
$attachmentOutput | ForEach-Object { Write-Host $_ }

$remoteAttachment = ($attachmentOutput | Where-Object { $_ -match '^ATTACHMENT_ARCHIVE=/' } | Select-Object -Last 1) -replace '^ATTACHMENT_ARCHIVE=', ''
$remoteAttachmentChecksum = ($attachmentOutput | Where-Object { $_ -match '^ATTACHMENT_CHECKSUM=/' } | Select-Object -Last 1) -replace '^ATTACHMENT_CHECKSUM=', ''
if (-not $remoteAttachment -or -not $remoteAttachmentChecksum) {
    throw 'The Oracle server did not return the created attachment archive paths.'
}
$remoteAttachment=$remoteAttachment.Trim()
$remoteAttachmentChecksum=$remoteAttachmentChecksum.Trim()
$localAttachment=Join-Path $LocalBackupDirectory $remoteAttachment.Split('/')[-1]
$localAttachmentChecksum=Join-Path $LocalBackupDirectory $remoteAttachmentChecksum.Split('/')[-1]

Write-Host "Downloading $($remoteAttachment.Split('/')[-1]) ..." -ForegroundColor Cyan
Invoke-NativeChecked -Program 'scp.exe' -Arguments @('-i',$KeyPath,("{0}:{1}" -f $sshTarget,$remoteAttachment),$localAttachment)
Invoke-NativeChecked -Program 'scp.exe' -Arguments @('-i',$KeyPath,("{0}:{1}" -f $sshTarget,$remoteAttachmentChecksum),$localAttachmentChecksum)

if ((Get-Item -LiteralPath $localAttachment).Length -eq 0) { throw "Downloaded attachment archive is empty: $localAttachment" }
$expectedAttachmentHash=((Get-Content -LiteralPath $localAttachmentChecksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actualAttachmentHash=(Get-FileHash -LiteralPath $localAttachment -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedAttachmentHash -ne $actualAttachmentHash) { throw "SHA-256 verification failed for $localAttachment" }

Write-Host ''
Write-Host 'Oracle database + attachments backup completed successfully.' -ForegroundColor Green
Write-Host "Database:    $localBackup"
Write-Host "DB SHA-256: $actualHash"
Write-Host "Attachments: $localAttachment"
Write-Host "ATT SHA-256: $actualAttachmentHash"
