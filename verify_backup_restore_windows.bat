@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_backup_restore_windows.ps1" %*
set "verify_result=%ERRORLEVEL%"
if not "%verify_result%"=="0" echo Restore verification failed with exit code %verify_result%.
pause
exit /b %verify_result%
