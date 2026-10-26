@echo off
call "%~dp0launcher.cmd" monitor
set "launch_status=%errorlevel%"
pause
exit /b %launch_status%
