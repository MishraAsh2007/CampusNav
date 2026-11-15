@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo The project Python environment is missing.
    echo Open a terminal in this folder and run:
    echo   py -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -e ".[build,dev]"
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -u -m scripts.build_graph %*
set "build_result=%ERRORLEVEL%"
popd
exit /b %build_result%
