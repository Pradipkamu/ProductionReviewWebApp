$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'update_logs'
$updateCode = 1
$transcriptStarted = $false
try {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $logPath = Join-Path $logDirectory ('update_' + (Get-Date -Format 'yyyyMMdd_HHmmssfff') + '.log')
    Start-Transcript -LiteralPath $logPath -Force | Out-Null
    $transcriptStarted = $true
    Write-Host "Installation folder: $PSScriptRoot"
    Write-Host "Log file: $logPath"
    if (Test-Path -LiteralPath 'VERSION.txt') { Write-Host ('Package version: ' + (Get-Content -LiteralPath 'VERSION.txt' -Raw).Trim()) }
    $updater = Join-Path $PSScriptRoot 'update_in_place_windows.ps1'
    if (!(Test-Path -LiteralPath $updater)) { throw 'Extract both diagnostic files into the existing application folder beside update_in_place_windows.ps1.' }
    if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker command is unavailable. Start Docker Desktop and check its installation.' }
    # Run in a child PowerShell process: exit in the original updater cannot close this launcher.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updater
    $updateCode = $LASTEXITCODE
    if ($updateCode -ne 0) { Write-Host "Update failed with exit code $updateCode. The error output is recorded above." -ForegroundColor Red }
} catch {
    Write-Host ('Update failed: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ($_ | Out-String)
    $updateCode = 1
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null; Write-Host "Saved log: $logPath" }
}
exit $updateCode
