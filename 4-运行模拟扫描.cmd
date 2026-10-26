@echo off
call "%~dp0launcher.cmd" demo
set "launch_status=%errorlevel%"
pause
exit /b %launch_status%
