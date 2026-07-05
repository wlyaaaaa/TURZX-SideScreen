@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0repair-elevated.ps1" -Root "%cd%" -Port COM7 -IntervalMs 500
pause
