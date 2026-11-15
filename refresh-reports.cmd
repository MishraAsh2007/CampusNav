@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m scripts.refresh_reports %*
set "reports_result=%ERRORLEVEL%"
popd
exit /b %reports_result%
