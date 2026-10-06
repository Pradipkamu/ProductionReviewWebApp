@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ProductionReviewWebApp - Restore Oracle Data to Windows MIS
echo ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore_Oracle_Review_To_Windows.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo Restore helper ended with error code %RC%.
) else (
  echo Restore helper completed.
)
echo.
pause
exit /b %RC%
