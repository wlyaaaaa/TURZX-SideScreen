@echo off
setlocal
cd /d "%~dp0"
python turzx_weather_shim.py --host 127.0.0.1 --port 18080
