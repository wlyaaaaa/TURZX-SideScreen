@echo off
set SCRIPT=%~dp0InstallStartupTask-Admin.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoExit -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\"'"
