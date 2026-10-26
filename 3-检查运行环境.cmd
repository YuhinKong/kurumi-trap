@echo off
call "%~dp0launcher.cmd" check
set "launch_status=%errorlevel%"
pause
exit /b %launch_status%
