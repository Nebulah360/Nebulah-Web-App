@echo off
cd /d "%~dp0"
py -3 bridge\server.py %*
pause
