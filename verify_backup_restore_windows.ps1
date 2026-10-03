param([string]$BackupPath = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function DockerChecked([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Docker failed: ' + ($Arguments -join ' ')) }
}

if (-not $BackupPath) {
    $latest = Get-ChildItem database\backups\*.dump -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not $latest) { throw 'No .dump backup was found. Pass -BackupPath with a verified backup file.' }
    $BackupPath = $latest.FullName
}
if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf) -or (Get-Item -LiteralPath $BackupPath).Length -eq 0) {
    throw "Backup is missing or empty: $BackupPath"
}
$checksumPath = "$BackupPath.sha256"
if (Test-Path -LiteralPath $checksumPath -PathType Leaf) {
    $expectedHash = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0]
    $actualHash = (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash
    if ($expectedHash -ne $actualHash) { throw "Backup SHA-256 verification failed: $BackupPath" }
}

DockerChecked @('compose','up','-d','db')
$dbReady = $false
for ($i=0; $i -lt 30; $i++) {
    & docker compose exec -T db pg_isready -U pms -d pms | Out-Null
    if ($LASTEXITCODE -eq 0) { $dbReady = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $dbReady) { throw 'PostgreSQL did not become ready.' }

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddHHmmss')
$scratch = "pms_restore_verify_${stamp}_$PID"
$containerFile = "/tmp/$scratch.dump"
try {
    DockerChecked @('compose','cp',(Resolve-Path -LiteralPath $BackupPath).Path,"db:$containerFile")
    DockerChecked @('compose','exec','-T','db','pg_restore','--list',$containerFile)
    DockerChecked @('compose','exec','-T','db','createdb','-U','pms',$scratch)
    DockerChecked @('compose','exec','-T','db','pg_restore','-U','pms','-d',$scratch,'--no-owner','--no-privileges',$containerFile)
    $coreTables = (& docker compose exec -T db psql -U pms -d $scratch -Atc "SELECT CASE WHEN to_regclass('public.users') IS NOT NULL AND to_regclass('public.products') IS NOT NULL THEN 'OK' ELSE 'MISSING' END").Trim()
    if ($LASTEXITCODE -ne 0 -or $coreTables -ne 'OK') { throw 'Restore completed but required users/products tables are missing.' }
    Write-Host "Restore verification passed in isolated database $scratch. Live database pms was not modified."
}
finally {
    & docker compose exec -T db dropdb -U pms --if-exists --force $scratch | Out-Null
    & docker compose exec -T db rm -f $containerFile | Out-Null
}
