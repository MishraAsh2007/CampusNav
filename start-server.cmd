@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "VITE_CAMPUSNAV_INTEGRATED=1"
set "VITE_CAMPUSNAV_DEMO=0"
if /i "%~1"=="--memory" set "CAMPUSNAV_MEMORY=1"
if /i "%~1"=="--demo" (
    set "CAMPUSNAV_MEMORY=1"
    set "CAMPUSNAV_DEMO=1"
    set "VITE_CAMPUSNAV_DEMO=1"
)
set "campusnav_python=.venv\Scripts\python.exe"
if not exist "%campusnav_python%" if exist "..\..\.venv\Scripts\python.exe" set "campusnav_python=..\..\.venv\Scripts\python.exe"
if not exist "%campusnav_python%" (
    echo The project Python environment is missing. See README.md for setup.
    popd
    exit /b 1
)
if not defined ROUTING_GRAPH (
    if exist "data\umass-residences.graph.json" (
        set "ROUTING_GRAPH=data/umass-residences.graph.json"
    ) else (
        set "ROUTING_GRAPH=data/umass.graph.json"
    )
)
echo Graph: %ROUTING_GRAPH%
echo Checkout: %CD%
if not defined BUILDINGS_PATH set "BUILDINGS_PATH=data/residence_buildings.json"
if not defined PLAN_WAYFINDING_DIR set "PLAN_WAYFINDING_DIR=data/plan_wayfinding"
if not defined PLAN_PORTALS_PATH set "PLAN_PORTALS_PATH=data/plan_wayfinding_portals.json"
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
echo Open http://127.0.0.1:8000 after the integrated server starts. Keep this terminal open.
echo If port 8000 is already in use, stop the older server before restarting.
echo Data API: http://127.0.0.1:8000/api/data/docs
echo Backend diagnostics: http://127.0.0.1:8000/backend
echo API documentation: http://127.0.0.1:8000/docs
"%campusnav_python%" -m uvicorn campus_routing.integrated:app --host 127.0.0.1 --port 8000 %campusnav_env_args%
set "server_result=%ERRORLEVEL%"
popd
exit /b %server_result%
