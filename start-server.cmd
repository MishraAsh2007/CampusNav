@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if /i "%~1"=="--memory" set "CAMPUSNAV_MEMORY=1"
if /i "%~1"=="--demo" (
    set "CAMPUSNAV_MEMORY=1"
    set "CAMPUSNAV_DEMO=1"
)
if not exist ".venv\Scripts\python.exe" (
    echo The project Python environment is missing. See README.md for setup.
    popd
    exit /b 1
)
if not defined ROUTING_GRAPH (
    if exist "data\umass.graph.json" (
        set "ROUTING_GRAPH=data/umass.graph.json"
    ) else (
        set "ROUTING_GRAPH=data/demo.graph.json"
    )
)
echo Graph: %ROUTING_GRAPH%
if not exist "frontend\node_modules\.bin\vite.cmd" (
    call npm.cmd --prefix frontend ci
    if errorlevel 1 (
        popd
        exit /b 1
    )
)
call npm.cmd --prefix frontend run build
if errorlevel 1 (
    popd
    exit /b 1
)
set "campusnav_env_args="
if exist "backend\.env" set "campusnav_env_args=--env-file backend\.env"
echo Open http://127.0.0.1:8000 for the campus map. Keep this terminal open.
echo Data API: http://127.0.0.1:8000/api/data/docs
echo Backend diagnostics: http://127.0.0.1:8000/backend
echo API documentation: http://127.0.0.1:8000/docs
".venv\Scripts\python.exe" -m uvicorn campus_routing.integrated:app --host 127.0.0.1 --port 8000 %campusnav_env_args%
set "server_result=%ERRORLEVEL%"
popd
exit /b %server_result%
