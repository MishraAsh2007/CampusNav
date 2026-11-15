@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo The project Python environment is missing. See README.md for setup.
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -u -m scripts.refresh_notices %*
set "refresh_result=%ERRORLEVEL%"
popd
exit /b %refresh_result%
