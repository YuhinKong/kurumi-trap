@echo off
call "%~dp0launcher.cmd" app
set "launch_status=%errorlevel%"
pause
exit /b %launch_status%
