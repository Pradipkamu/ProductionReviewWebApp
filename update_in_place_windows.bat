@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_in_place_windows.ps1"
set "update_result=%ERRORLEVEL%"
if not "%update_result%"=="0" echo Update failed with exit code %update_result%. Read the error above.
pause
exit /b %update_result%
