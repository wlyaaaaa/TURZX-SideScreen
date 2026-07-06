@echo off
set "SCRIPT=%~dp0install-startup-admin.ps1"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%SCRIPT%"" -Root ""%ROOT%""'"
