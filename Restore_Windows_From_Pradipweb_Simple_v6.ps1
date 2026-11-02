[CmdletBinding()]
param(
    [string]$ServerHost = "137.23.40.188",
    [string]$ServerUser = "ubuntu",
    [string]$KeyPath = "$HOME\.ssh\pradipweb.key",
    [string]$AppPath = "D:\Machine Shop MIS"
)

$ErrorActionPreference = "Stop"
$RemoteDb = "/home/ubuntu/pradipweb_live.dump"
$RemoteAtt = "/home/ubuntu/pradipweb_live_attachments.tar.gz"
$LocalDb = Join-Path $env:TEMP "pradipweb_live.dump"
$LocalAtt = Join-Path $env:TEMP "pradipweb_live_attachments.tar.gz"
$Target = "$ServerUser@$ServerHost"

function Run-SSH([string]$Command) {
    & ssh.exe -i $KeyPath -o BatchMode=yes $Target $Command
    if ($LASTEXITCODE -ne 0) { throw "SSH command failed ($LASTEXITCODE): $Command" }
}
function Run-SCP([string]$Source, [string]$Destination) {
    & scp.exe -i $KeyPath -o BatchMode=yes $Source $Destination
    if ($LASTEXITCODE -ne 0) { throw "SCP failed ($LASTEXITCODE): $Source" }
}
function Run-Docker([string[]]$DockerArgs) {
    & docker.exe @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed ($LASTEXITCODE): docker $($DockerArgs -join ' ')" }
}
function Save-CurrentStateBackup([string]$Stamp) {
    $backupRoot = "D:\MIS Machine Shops Back Up"
    $backupSet = Join-Path $backupRoot "Pradipweb_Restore_$Stamp"
    New-Item -ItemType Directory -Force -Path $backupSet | Out-Null

    $backupFile = Join-Path $backupSet "pms.dump"
    $attachmentsFile = Join-Path $backupSet "attachments.tar.gz"
    $containerBackup = "/tmp/pms_pradipweb_restored_$Stamp.dump"
    $attachDir = Join-Path $AppPath "database\attachments"

    Write-Host "Saving database backup to $backupFile ..."
    Run-Docker @("compose","exec","-T","db","pg_dump","-U","pms","-d","pms","-Fc","-f",$containerBackup)
    Run-Docker @("compose","cp","db:$containerBackup",$backupFile)
    if (!(Test-Path -LiteralPath $backupFile) -or (Get-Item -LiteralPath $backupFile).Length -eq 0) {
        throw "Database backup file was not created or is empty: $backupFile"
    }

    if (!(Test-Path -LiteralPath $attachDir -PathType Container)) {
        throw "Attachments folder not found; database backup exists but attachment backup could not be made: $attachDir"
    }
    Write-Host "Saving attachments backup to $attachmentsFile ..."
    & tar.exe -czf $attachmentsFile -C (Join-Path $AppPath "database") "attachments"
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $attachmentsFile) -or (Get-Item -LiteralPath $attachmentsFile).Length -eq 0) {
        throw "Attachments archive was not created correctly. Database dump is retained at: $backupFile"
    }

    $attachmentCount = @(Get-ChildItem -LiteralPath $attachDir -File -Recurse -ErrorAction Stop).Count
    $dbHash = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $attachmentsHash = (Get-FileHash -LiteralPath $attachmentsFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $dbSummary = & docker.exe compose exec -T db psql -U pms -d pms -Atc "SELECT concat((SELECT version_num FROM alembic_version), chr(124), (SELECT count(*) FROM products), chr(124), (SELECT count(*) FROM daily_mis), chr(124), (SELECT count(*) FROM actions))"
    $summaryExit = $LASTEXITCODE
    if ($summaryExit -ne 0 -or [string]::IsNullOrWhiteSpace(($dbSummary -join ""))) {
        throw "Database and attachment backups exist, but migration/count metadata could not be read. Keep backup folder: $backupSet"
    }

    $metaFile = Join-Path $backupSet "backup_details.txt"
    @(
        "Backup created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
        "Database: pms"
        "Migration | Products | Daily MIS | Actions"
        ($dbSummary -join "").Trim()
        "Attachment files: $attachmentCount"
        "Database SHA256: $dbHash"
        "Attachments SHA256: $attachmentsHash"
        "Database dump: $backupFile"
        "Attachments archive: $attachmentsFile"
    ) | Set-Content -LiteralPath $metaFile -Encoding UTF8

    Write-Host "Database backup saved: $backupFile" -ForegroundColor Green
    Write-Host "Attachments backup saved: $attachmentsFile" -ForegroundColor Green
    Write-Host "Backup details: $metaFile"
    Write-Host "Attachment files included: $attachmentCount"
}

try {
    if (!(Test-Path (Join-Path $AppPath "docker-compose.yml")) -and !(Test-Path (Join-Path $AppPath "compose.yml"))) {
        throw "Docker Compose file not found in $AppPath"
    }
    Set-Location $AppPath

    Write-Host ""
    Write-Host "1 = Restore Windows database and attachments from Pradipweb (then save dated database + attachment backups)"
    Write-Host "2 = Save a dated backup of the current Windows database + attachments only (no restore)"
    $mode = Read-Host "Select 1 or 2"
    if ($mode -eq "2") {
        Save-CurrentStateBackup (Get-Date -Format "yyyyMMdd_HHmmss")
        exit 0
    }
    if ($mode -ne "1") { throw "Invalid selection. Enter 1 or 2." }
    if (!(Test-Path $KeyPath)) { throw "SSH key not found: $KeyPath" }

    Write-Host "1/7 Creating fresh live database backup on Pradipweb..."
    Run-SSH "cd /home/ubuntu/ProductionReviewWebApp && docker compose exec -T db pg_dump -U pms -d pms -Fc > $RemoteDb && test -s $RemoteDb"

    Write-Host "2/7 Creating matching attachments backup (sudo handles protected files)..."
    Run-SSH "sudo tar -czf $RemoteAtt -C /home/ubuntu/ProductionReviewWebApp/database attachments && sudo chown ubuntu:ubuntu $RemoteAtt && chmod 600 $RemoteAtt && test -s $RemoteAtt"

    Write-Host "3/7 Downloading live backups..."
    Run-SCP "${Target}:$RemoteDb" $LocalDb
    Run-SCP "${Target}:$RemoteAtt" $LocalAtt

    Write-Host "4/7 Checking downloaded backup files..."
    if (!(Test-Path $LocalDb) -or (Get-Item $LocalDb).Length -eq 0) { throw "Database backup is missing or empty." }
    if (!(Test-Path $LocalAtt) -or (Get-Item $LocalAtt).Length -eq 0) { throw "Attachments backup is missing or empty." }
    $remoteDbHash = (& ssh.exe -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 $Target "sha256sum $RemoteDb").Split(' ')[0]
    if ($LASTEXITCODE -ne 0) { throw "Could not verify remote database checksum." }
    $localDbHash = (Get-FileHash $LocalDb -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($remoteDbHash.Trim().ToLowerInvariant() -ne $localDbHash) { throw "Database checksum mismatch." }
    $remoteAttHash = (& ssh.exe -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 $Target "sha256sum $RemoteAtt").Split(' ')[0]
    if ($LASTEXITCODE -ne 0) { throw "Could not verify remote attachments checksum." }
    $localAttHash = (Get-FileHash $LocalAtt -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($remoteAttHash.Trim().ToLowerInvariant() -ne $localAttHash) { throw "Attachments checksum mismatch." }

    Write-Host "5/7 Checking the live source record counts..."
    Run-SSH "cd /home/ubuntu/ProductionReviewWebApp && docker compose exec -T db psql -U pms -d pms -Atc 'SELECT concat((SELECT count(*) FROM products), chr(124), (SELECT count(*) FROM daily_mis), chr(124), (SELECT count(*) FROM actions))'"

    Write-Host "Live source counts are shown above."

    Write-Host ""
    Write-Host "This replaces the Windows pms database and database\attachments with Pradipweb live data."
    if ((Read-Host "Type REPLACE-WINDOWS to continue") -cne "REPLACE-WINDOWS") {
        Write-Host "Cancelled. Windows database and attachments were not changed."
        exit 0
    }

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $rollback = Join-Path $AppPath "database\before_pradipweb_$stamp"
    New-Item -ItemType Directory -Force -Path $rollback | Out-Null

    Write-Host "6/7 Saving Windows rollback copies..."
    Run-Docker @("compose","exec","-T","db","pg_dump","-U","pms","-d","pms","-Fc","-f","/tmp/windows_before_pradipweb.dump")
    Run-Docker @("compose","cp","db:/tmp/windows_before_pradipweb.dump",(Join-Path $rollback "windows_before.dump"))
    $attachDir = Join-Path $AppPath "database\attachments"
    if (Test-Path $attachDir) { Copy-Item $attachDir (Join-Path $rollback "attachments") -Recurse -Force }

    Write-Host "7/7 Restoring Pradipweb data..."
    Run-Docker @("compose","stop","backend")
    Run-Docker @("compose","cp",$LocalDb,"db:/tmp/pradipweb_live.dump")
    Run-Docker @("compose","exec","-T","db","dropdb","-U","pms","--if-exists","pms")
    Run-Docker @("compose","exec","-T","db","createdb","-U","pms","-O","pms","pms")
    Run-Docker @("compose","exec","-T","db","pg_restore","-U","pms","-d","pms","--no-owner","--no-privileges","/tmp/pradipweb_live.dump")

    $stage = Join-Path $env:TEMP "pradipweb_attachments_extract"
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    & tar.exe -xzf $LocalAtt -C $stage
    if ($LASTEXITCODE -ne 0 -or !(Test-Path (Join-Path $stage "attachments"))) { throw "Could not extract Pradipweb attachments." }
    if (Test-Path $attachDir) { Rename-Item $attachDir "attachments_before_pradipweb_$stamp" }
    Move-Item (Join-Path $stage "attachments") $attachDir

    Run-Docker @("compose","up","-d","backend","frontend")
    Start-Sleep -Seconds 15
    Run-Docker @("compose","exec","-T","db","pg_isready","-U","pms","-d","pms")
    Run-Docker @("compose","exec","-T","db","psql","-U","pms","-d","pms","-c","SELECT version_num FROM alembic_version;")
    Run-Docker @("compose","exec","-T","db","psql","-U","pms","-d","pms","-c","SELECT (SELECT count(*) FROM products) AS products, (SELECT count(*) FROM daily_mis) AS daily_mis, (SELECT count(*) FROM actions) AS actions;")

    Write-Host ""
    Write-Host "8/8 Saving restored Windows database + attachments to the MIS backup folder..."
    Save-CurrentStateBackup $stamp

    Write-Host "Restore commands completed and verified." -ForegroundColor Green
    Write-Host "MIS backup folder: D:\MIS Machine Shops Back Up\Pradipweb_Restore_$stamp"
    Write-Host "Windows rollback copy: $rollback"
    Write-Host "Downloaded source backups: $LocalDb and $LocalAtt"
    Write-Host "Keep the rollback copy until the application has been checked."
}
catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "No automatic rollback is attempted. If restore had started, keep the rollback dump, rollback attachments, and downloaded source backups."
    exit 1
}
