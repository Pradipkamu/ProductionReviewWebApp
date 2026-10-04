@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rotate_database_password_windows.ps1" %*
set "result=%ERRORLEVEL%"
if not "%result%"=="0" echo Database password rotation failed with exit code %result%.
pause
exit /b %result%
