@echo off
cd /d %~dp0
echo === Backend ===
docker compose logs --tail=180 backend
echo.
echo === Frontend ===
docker compose logs --tail=100 frontend
pause
