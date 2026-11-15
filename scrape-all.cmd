@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python environment first. See README.md.
  popd
  exit /b 1
)
".venv\Scripts\python.exe" -u -m scripts.scrape_all %*
set "scrape_result=%ERRORLEVEL%"
popd
exit /b %scrape_result%
