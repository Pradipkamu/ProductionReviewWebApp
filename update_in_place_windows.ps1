$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\configure_env.ps1"
New-Item -ItemType Directory -Force database\backups | Out-Null
function DockerChecked([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Docker failed: ' + ($Arguments -join ' ')) }
}
DockerChecked @('compose','build','backend','frontend')
# Validate the newly built source before stopping the currently running app.
# This catches partially copied update packages (for example, a stale auth.py).
DockerChecked @('compose','run','--rm','--no-deps','backend','python','-m','app.preflight')
DockerChecked @('compose','up','-d','db')
$dbReady = $false
for ($i=0; $i -lt 30; $i++) {
    & docker compose exec -T db pg_isready -U pms -d pms | Out-Null
    if ($LASTEXITCODE -eq 0) { $dbReady = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $dbReady) { throw 'PostgreSQL did not become ready; no backup or migration was attempted.' }
DockerChecked @('compose','stop','frontend','backend')
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$backup = "database/backups/pms_before_update_$stamp.dump"
# Write binary dump inside container; avoid Windows PowerShell text redirection.
DockerChecked @('compose','exec','-T','db','sh','-c','pg_dump -U pms -d pms -Fc -f /tmp/pms_pre_update.dump')
DockerChecked @('compose','exec','-T','db','pg_restore','--list','/tmp/pms_pre_update.dump')
DockerChecked @('compose','cp','db:/tmp/pms_pre_update.dump',$backup)
if ((Get-Item $backup).Length -eq 0) { throw 'Empty backup; refusing to update.' }
$backupHash = (Get-FileHash $backup -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$backup.sha256", $backupHash + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
DockerChecked @('compose','up','-d','--no-deps','backend','frontend')
for ($i=0; $i -lt 40; $i++) {
    try {
        $health = Invoke-RestMethod http://localhost:8000/api/health -TimeoutSec 2
        if ($health.status -eq 'ok') { Write-Host "Update ready. Verified backup: $backup"; exit 0 }
    } catch { }
    Start-Sleep -Seconds 2
}
& docker compose logs --tail=100 backend
throw 'Backend health check failed. Keep backup and follow docs/UPDATE_v0.3.0.md.'
