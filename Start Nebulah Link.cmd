@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start-local.ps1" %*
set "nebulahExit=%ERRORLEVEL%"
if not "%nebulahExit%"=="0" pause
exit /b %nebulahExit%
