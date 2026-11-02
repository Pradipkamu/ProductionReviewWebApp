@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore_Windows_From_Pradipweb_Simple_v6.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo RESTORE OR BACKUP FAILED. Keep all backup files.
pause
exit /b %RC%
