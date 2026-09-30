@echo off
cd /d %~dp0
docker compose down
echo Application stopped. Persistent data remains in database\.
pause
