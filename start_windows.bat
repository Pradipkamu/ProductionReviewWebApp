@echo off
setlocal
cd /d %~dp0

if not exist .env copy .env.example .env >nul
if not exist database\postgres mkdir database\postgres
if not exist database\backups mkdir database\backups
if not exist database\imports mkdir database\imports
if not exist database\attachments mkdir database\attachments

echo Checking Docker Desktop...
docker info >nul 2>&1
if errorlevel 1 (
  echo.
  echo Docker Desktop is not running or Docker Engine is not ready.
  echo Start Docker Desktop, wait until the engine is running, then try again.
  pause
  exit /b 1
)

echo Docker is running.
echo Building and starting Production Review Manager v0.2.9...
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo Application build/start failed. Showing recent logs:
  docker compose logs --tail=150 backend frontend
  pause
  exit /b 1
)

echo Waiting for backend...
set /a tries=0
:wait_backend
set /a tries+=1
curl -fsS http://localhost:8000/api/health >nul 2>&1
if not errorlevel 1 goto backend_ready
if %tries% GEQ 40 goto backend_failed
timeout /t 2 /nobreak >nul
goto wait_backend

:backend_failed
echo.
echo Backend did not become ready. Showing backend logs:
docker compose logs --tail=180 backend
pause
exit /b 1

:backend_ready
echo Backend is ready.
echo.
echo Application: http://localhost:5173
echo API docs:    http://localhost:8000/docs
echo Database:    %CD%\database\postgres
start http://localhost:5173
pause
endlocal
