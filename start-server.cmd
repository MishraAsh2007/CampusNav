@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
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
if not exist "frontend\dist\index.html" (
    echo Building the map interface...
    pushd frontend
    call npm.cmd run build
    if errorlevel 1 (
        popd
        popd
        exit /b 1
    )
    popd
)
echo Open http://127.0.0.1:8000 for the campus map. Keep this terminal open.
echo Scraper updates: run refresh-notices.cmd --rules-only --watch in a second terminal.
echo The map polls saved notices every 15 seconds. The scraper refreshes them hourly.
echo Backend diagnostics: http://127.0.0.1:8000/backend
echo API documentation: http://127.0.0.1:8000/docs
".venv\Scripts\python.exe" -m uvicorn campus_routing.api:app --host 127.0.0.1 --port 8000
set "server_result=%ERRORLEVEL%"
popd
exit /b %server_result%
