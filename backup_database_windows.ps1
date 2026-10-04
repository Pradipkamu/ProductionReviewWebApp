$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force database\backups | Out-Null

function DockerChecked([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Docker failed: ' + ($Arguments -join ' ')) }
}

DockerChecked @('compose','up','-d','db')
$ready=$false
for($i=0;$i -lt 30;$i++){
    & docker compose exec -T db pg_isready -U pms -d pms | Out-Null
    if($LASTEXITCODE -eq 0){$ready=$true;break}
    Start-Sleep -Seconds 2
}
if(!$ready){throw 'PostgreSQL did not become ready.'}

$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$backup=Join-Path $PSScriptRoot "database\backups\pms_$stamp.dump"
$container='/tmp/pms_manual_backup.dump'
try{
    DockerChecked @('compose','exec','-T','db','pg_dump','-U','pms','-d','pms','-Fc','-f',$container)
    DockerChecked @('compose','exec','-T','db','pg_restore','--list',$container)
    DockerChecked @('compose','cp',"db:$container",$backup)
    if((Get-Item -LiteralPath $backup).Length -eq 0){throw 'Backup is empty; refusing to keep it.'}
    $hash=(Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$backup.sha256",$hash+[Environment]::NewLine,(New-Object Text.UTF8Encoding($false)))
    Write-Host "Verified custom-format backup created: $backup"
    Write-Host "SHA-256: $hash"
}
finally{
    & docker compose exec -T db rm -f $container | Out-Null
}
