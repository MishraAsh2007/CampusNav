@echo off
setlocal
pushd "%~dp0"
if not exist "data\umass-residences.graph.json" (
    echo The expanded graph is missing. See docs\ALL_RESIDENCE_ROUTES.md.
    popd
    exit /b 1
)
if not exist "data\residence_buildings.json" (
    echo The residence catalog is missing. Run scripts.build_residence_catalog first.
    popd
    exit /b 1
)
set "ROUTING_GRAPH=data/umass-residences.graph.json"
set "BUILDINGS_PATH=data/residence_buildings.json"
call start-server.cmd
popd
