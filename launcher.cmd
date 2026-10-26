@echo off
setlocal
set "PYTHONUTF8=1"
pushd "%~dp0"
if errorlevel 1 goto fail
if not exist ".venv\Scripts\python.exe" goto create_env
goto dependencies
:create_env
python -m venv .venv
if errorlevel 1 goto fail
:dependencies
".venv\Scripts\python.exe" -c "import akshare,streamlit,plotly,pandas,requests,pytest" >nul 2>&1
if errorlevel 1 goto install_dependencies
goto dispatch
:install_dependencies
".venv\Scripts\python.exe" -m pip install --no-cache-dir -r requirements.txt
if errorlevel 1 goto fail
:dispatch
if "%~1"=="" goto app
if /i "%~1"=="app" goto app
if /i "%~1"=="monitor" goto tool
if /i "%~1"=="market-worker" goto tool
if /i "%~1"=="check" goto tool
if /i "%~1"=="demo" goto tool
if /i "%~1"=="selftest" goto selftest
echo Usage: launcher.cmd app, monitor, check, demo or selftest
popd
exit /b 2
:tool
".venv\Scripts\python.exe" -m monitor.cli "%~1"
if errorlevel 1 goto fail
goto done
:app
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 goto fail
goto done
:selftest
".venv\Scripts\python.exe" -c "from pathlib import Path; import sys; assert Path('app.py').is_file(); print('Launcher OK'); print(sys.prefix)"
if errorlevel 1 goto fail
:done
popd
exit /b 0
:fail
echo Launch failed. Review the error above.
popd
exit /b 1
