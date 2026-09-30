@echo off
setlocal
cd /d %~dp0
if not exist database\backups mkdir database\backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
set FILE=database\backups\pms_%TS%.sql
echo Creating backup %FILE% ...
docker compose exec -T db pg_dump -U pms -d pms > "%FILE%"
if errorlevel 1 (
  echo Backup failed.
  del "%FILE%" >nul 2>&1
  pause
  exit /b 1
)
echo Backup completed: %FILE%
pause
endlocal
