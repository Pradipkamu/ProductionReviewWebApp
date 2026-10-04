$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$created = !(Test-Path .env)
if ($created) { Copy-Item .env.example .env }
$path = Join-Path $PSScriptRoot '.env'
$text = [IO.File]::ReadAllText($path)

function Get-EnvValue([string]$Name) {
    $m = [regex]::Match($script:text, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    return $null
}
function Set-EnvValue([string]$Name, [string]$Value) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    if ([regex]::IsMatch($script:text, $pattern)) {
        $script:text = [regex]::Replace($script:text, $pattern, ($Name + '=' + $Value))
    } else {
        $script:text = $script:text.TrimEnd() + "`n" + $Name + '=' + $Value + "`n"
    }
}
function New-RandomHex([int]$Bytes) {
    $buf = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buf) } finally { $rng.Dispose() }
    return -join ($buf | ForEach-Object { $_.ToString('x2') })
}

$secret = Get-EnvValue 'SECRET_KEY'
if (!$secret -or $secret -match '(?i)change|dev-secret') {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    Set-EnvValue 'SECRET_KEY' ([Convert]::ToBase64String($bytes))
}

$dbPlaceholder = ((Get-EnvValue 'POSTGRES_PASSWORD') -match '(?i)^CHANGE_') -or ((Get-EnvValue 'DATABASE_URL') -match '(?i)CHANGE_THIS')
if ($created -or $dbPlaceholder) {
    $dbPassword = New-RandomHex 24
    Set-EnvValue 'POSTGRES_PASSWORD' $dbPassword
    Set-EnvValue 'DATABASE_URL' ("postgresql+psycopg://pms:$dbPassword@db:5432/pms")
}
if ($created) {
    $adminPassword = Get-EnvValue 'ADMIN_PASSWORD'
    if (!$adminPassword -or $adminPassword -eq 'ChangeMe123!' -or $adminPassword -match '(?i)change') {
        Set-EnvValue 'ADMIN_PASSWORD' ('Init-' + (New-RandomHex 12) + '!9aA')
    }
}

[IO.File]::WriteAllText($path, $text.TrimEnd() + "`n", (New-Object Text.UTF8Encoding($false)))
Write-Host 'Environment initialized; existing non-placeholder settings preserved.'
if ($created) {
    Write-Host 'Fresh-install application/database credentials were generated in .env.'
} else {
    $dbUrl = Get-EnvValue 'DATABASE_URL'
    if ($dbUrl -match ':pms@db:5432/pms' -or $dbUrl -match 'CHANGE_THIS') {
        Write-Warning 'Legacy/default database password detected; run rotate_database_password_windows.ps1.'
    }
    if ((Get-EnvValue 'ADMIN_PASSWORD') -eq 'ChangeMe123!') {
        Write-Warning 'Bootstrap ADMIN_PASSWORD is still the legacy default; change it in .env after confirming the real admin account password.'
    }
}
