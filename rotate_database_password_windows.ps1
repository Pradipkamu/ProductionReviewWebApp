param([string]$NewPassword = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\configure_env.ps1"

function DockerChecked([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Docker failed: ' + ($Arguments -join ' ')) }
}
function New-RandomHex([int]$Bytes) {
    $buf = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buf) } finally { $rng.Dispose() }
    return -join ($buf | ForEach-Object { $_.ToString('x2') })
}
function Set-EnvValue([string]$Text, [string]$Name, [string]$Value) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    if ([regex]::IsMatch($Text, $pattern)) {
        return [regex]::Replace($Text, $pattern, ($Name + '=' + $Value))
    }
    return $Text.TrimEnd() + "`n" + $Name + '=' + $Value + "`n"
}

if (!$NewPassword) { $NewPassword = New-RandomHex 24 }
if ($NewPassword -notmatch '^[A-Za-z0-9._~-]{24,128}$') {
    throw 'Database password must be 24-128 URL-safe characters: A-Z a-z 0-9 . _ ~ -'
}

DockerChecked @('compose','up','-d','db')
$ready = $false
for ($i=0; $i -lt 30; $i++) {
    & docker compose exec -T db pg_isready -U pms -d pms | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready=$true; break }
    Start-Sleep -Seconds 2
}
if (!$ready) { throw 'PostgreSQL did not become ready.' }

$path = Join-Path $PSScriptRoot '.env'
$originalText = [IO.File]::ReadAllText($path)
$text = $originalText
$encoded = [uri]::EscapeDataString($NewPassword)
$text = Set-EnvValue $text 'POSTGRES_PASSWORD' $NewPassword
$text = Set-EnvValue $text 'DATABASE_URL' ("postgresql+psycopg://pms:$encoded@db:5432/pms")
[IO.File]::WriteAllText($path, $text.TrimEnd() + "`n", (New-Object Text.UTF8Encoding($false)))

$sqlPassword = $NewPassword.Replace("'","''")
try {
    DockerChecked @('compose','exec','-T','db','psql','-U','pms','-d','pms','-v','ON_ERROR_STOP=1','-c',"ALTER ROLE pms WITH PASSWORD '$sqlPassword';")
} catch {
    [IO.File]::WriteAllText($path, $originalText, (New-Object Text.UTF8Encoding($false)))
    throw
}

DockerChecked @('compose','up','-d','--force-recreate','backend')
for ($i=0; $i -lt 40; $i++) {
    try {
        $health = Invoke-RestMethod http://localhost:8000/api/health -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Host 'Database password rotated and backend reconnected successfully.'
            Write-Host 'The new password is stored only in .env. Keep that file private.'
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 2
}
throw 'Password was changed, but backend health did not recover. Check .env and docker compose logs backend.'
