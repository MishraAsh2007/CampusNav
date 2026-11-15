@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m scripts.login_notices %*
set "login_result=%ERRORLEVEL%"
popd
exit /b %login_result%
