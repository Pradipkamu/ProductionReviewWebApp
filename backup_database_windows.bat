@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_database_windows.ps1" %*
set "result=%ERRORLEVEL%"
if not "%result%"=="0" echo Backup failed with exit code %result%.
pause
exit /b %result%
