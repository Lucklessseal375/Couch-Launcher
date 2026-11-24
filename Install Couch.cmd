@echo off
rem Double-click to set up Couch on this PC. Runs install-couch.ps1 even where Windows blocks PowerShell scripts.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-couch.ps1"
echo.
pause
