param(
    [string]$OracleHost = '92.4.90.35',
    [string]$OracleUser = 'ubuntu',
    [string]$KeyPath = "$HOME\.ssh\ssh-key-2026-07-23.key",
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
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    $outputLines = @($nativeOutput | ForEach-Object { $_.ToString() })
    if ($null -eq $nativeExitCode -or $nativeExitCode -ne 0) {
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

latest=$(find "$APP_PATH/database/backups" -maxdepth 1 -type f -name 'pms_*.dump' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$latest"
sudo test -s "$latest"

checksum="${latest}.sha256"
if ! sudo test -s "$checksum"; then
    actual=$(sudo sha256sum "$latest" | awk '{print $1}')
    printf '%s\n' "$actual" | sudo tee "$checksum" >/dev/null
fi

owner=$(id -un)
group=$(id -gn)
sudo chown "$owner:$group" "$latest" "$checksum"
sudo chmod 640 "$latest" "$checksum"

printf '__BACKUP__=%s\n' "$latest"
printf '__CHECKSUM__=%s\n' "$checksum"
'@

$remoteScript = $remoteScript.Replace('__APP_PATH__', $RemoteAppPath)
$sshTarget = "$OracleUser@$OracleHost"
$remoteOutput = @(Invoke-NativeChecked -Program 'ssh.exe' -Arguments @(
    '-T', '-i', $KeyPath, $sshTarget, 'tr -d ''\r'' | bash -s'
) -InputText $remoteScript)
$remoteOutput | ForEach-Object { Write-Host $_ }

$backupMarker = $remoteOutput | Where-Object { $_ -like '__BACKUP__=*' } | Select-Object -Last 1
$checksumMarker = $remoteOutput | Where-Object { $_ -like '__CHECKSUM__=*' } | Select-Object -Last 1
if (-not $backupMarker -or -not $checksumMarker) {
    throw 'The Oracle server did not return the created backup paths.'
}

$remoteBackup = ($backupMarker -replace '^__BACKUP__=', '').Trim()
$remoteChecksum = ($checksumMarker -replace '^__CHECKSUM__=', '').Trim()
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
Write-Host 'Oracle database backup downloaded and verified successfully.' -ForegroundColor Green
Write-Host "Backup:  $localBackup"
Write-Host "Checksum: $localChecksum"
Write-Host "SHA-256:  $actualHash"
