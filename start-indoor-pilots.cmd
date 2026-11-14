@echo off
setlocal
pushd "%~dp0"
if not exist "data\private\plan_wayfinding\oak.json" (
    echo Prepare the indoor sources first. See docs\EXPANDED_INDOOR_PILOTS.md.
    popd
    exit /b 1
)
set "PLAN_WAYFINDING_DIR=data/private/plan_wayfinding"
set "ROUTING_GRAPH=data/umass-residences.graph.json"
set "BUILDINGS_PATH=data/residence_buildings.json"
echo Open http://127.0.0.1:8004/docs for drawing and landmark wayfinding.
".venv\Scripts\python.exe" -m uvicorn campus_routing.api:app --host 127.0.0.1 --port 8004
popd
