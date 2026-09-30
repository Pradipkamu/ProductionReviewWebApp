$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .env)) { Copy-Item .env.example .env }
$text = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '.env'))
$match = [regex]::Match($text, '(?m)^SECRET_KEY=(.*)$')
if (!$match.Success -or !$match.Groups[1].Value.Trim() -or $match.Groups[1].Value -match '(?i)change|dev-secret') {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    $secret = [Convert]::ToBase64String($bytes)
    if ($match.Success) { $text = [regex]::Replace($text, '(?m)^SECRET_KEY=.*$', ('SECRET_KEY=' + $secret)) }
    else { $text += "`nSECRET_KEY=$secret`n" }
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), $text, (New-Object Text.UTF8Encoding($false)))
}
Write-Host 'Environment initialized; existing secret and database settings preserved.'
