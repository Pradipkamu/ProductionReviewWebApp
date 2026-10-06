@echo off
setlocal
cd /d "%~dp0"
echo Starting update with logging...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update_With_Log.ps1"
set "update_result=%ERRORLEVEL%"
echo.
if "%update_result%"=="0" (
 echo Update completed successfully.
) else (
 echo Update failed. Exit code: %update_result%
 echo Read the error above and the latest file in update_logs.
)
echo.
echo Press any key to close this window.
pause >nul
exit /b %update_result%
