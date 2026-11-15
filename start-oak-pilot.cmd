@echo off
setlocal
pushd "%~dp0"
".venv\Scripts\python.exe" -m scripts.trace_oak_wayfinding
if errorlevel 1 (
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -m scripts.expand_oak_wayfinding
if errorlevel 1 (
    popd
    exit /b 1
)
set "PLAN_WAYFINDING_DIR=data/private/plan_wayfinding"
set "ROUTING_GRAPH=data/umass-residences.graph.json"
set "BUILDINGS_PATH=data/residence_buildings.json"
echo Open http://127.0.0.1:8004/docs and expand Drawing wayfinding pilot.
".venv\Scripts\python.exe" -m uvicorn campus_routing.api:app --host 127.0.0.1 --port 8004
popd
