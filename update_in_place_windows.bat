@echo off
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_in_place_windows.ps1"
if errorlevel 1 exit /b 1
pause
