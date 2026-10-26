@echo off
call "%~dp0launcher.cmd" market-worker
set "result=%errorlevel%"
pause
exit /b %result%
