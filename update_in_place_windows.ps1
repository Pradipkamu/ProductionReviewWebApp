$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\configure_env.ps1"
New-Item -ItemType Directory -Force database\backups | Out-Null
function DockerChecked([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Docker failed: ' + ($Arguments -join ' ')) }
}
DockerChecked @('compose','build','backend','frontend')
DockerChecked @('compose','exec','-T','db','pg_isready','-U','pms','-d','pms')
DockerChecked @('compose','stop','frontend','backend')
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$backup = "database/backups/pms_before_v041_$stamp.dump"
# Write binary dump inside container; avoid Windows PowerShell text redirection.
DockerChecked @('compose','exec','-T','db','sh','-c','pg_dump -U pms -d pms -Fc -f /tmp/pms_pre_update.dump')
DockerChecked @('compose','exec','-T','db','pg_restore','--list','/tmp/pms_pre_update.dump')
DockerChecked @('compose','cp','db:/tmp/pms_pre_update.dump',$backup)
if ((Get-Item $backup).Length -eq 0) { throw 'Empty backup; refusing to update.' }
(Get-FileHash $backup -Algorithm SHA256).Hash | Set-Content "$backup.sha256"
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
