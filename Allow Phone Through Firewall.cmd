@echo off
setlocal
if exist "%~dp0Nebulah-Link.exe" (
  "%~dp0Nebulah-Link.exe" --allow-phone %*
) else (
  call "%~dp0Start Nebulah Link.cmd" --allow-phone %*
)
exit /b %ERRORLEVEL%
