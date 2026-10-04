param([string]$BackupPath = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\configure_env.ps1"

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

$actualHash=(Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath="$BackupPath.sha256"
if(Test-Path -LiteralPath $checksumPath -PathType Leaf){
    $expectedHash=((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    if($expectedHash -ne $actualHash){throw "Backup SHA-256 verification failed: $BackupPath"}
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
    $schemaVersion=(& docker compose exec -T db psql -U pms -d $scratch -Atc "SELECT COALESCE((SELECT version_num FROM alembic_version LIMIT 1),'unversioned')").Trim()
    if($LASTEXITCODE -ne 0){throw 'Could not read restored schema version.'}
    $marker=[ordered]@{
        status='ok'
        verified_at=[DateTime]::UtcNow.ToString('o')
        backup_file=(Split-Path -Leaf $BackupPath)
        backup_sha256=$actualHash
        schema_version=$schemaVersion
        core_tables='OK'
    }
    $marker | ConvertTo-Json | Set-Content -LiteralPath 'database\backups\restore_verification.json' -Encoding UTF8
    Write-Host "Restore verification passed in isolated database $scratch. Live database pms was not modified."
    Write-Host 'Verification marker updated: database\backups\restore_verification.json'
}
finally {
    & docker compose exec -T db dropdb -U pms --if-exists --force $scratch | Out-Null
    & docker compose exec -T db rm -f $containerFile | Out-Null
}
