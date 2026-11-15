@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m scripts.refresh_indoor_sources %*
set "refresh_result=%ERRORLEVEL%"
popd
exit /b %refresh_result%
