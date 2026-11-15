# Current map, routing, scraper, and Data API integration

The latest routing/scraper additions are layered on the combined `main` application.
The existing Role 2 UI, MongoDB/Data API bridge, upload endpoints, and explicit demo
mode remain supported. There is one application origin in the standard launcher.

Live mode uses our saved UMass/OSM building catalog, backend graph, and source-based
indoor maps. It does not substitute the Role 2 sample floor layouts, alternate
browser graph, seeded outage reports, or sample building accessibility attributes
when the backend is missing. Static markers can use `data/residence_buildings.json`;
routes and indoor maps remain unavailable until the source backend connects.
The planner shows that connection failure explicitly. Fictional layouts and the
browser router remain available only with `VITE_CAMPUSNAV_DEMO=1`.

## Start the application

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[pipeline,scraper,data,dev,build]"
npm.cmd --prefix frontend ci
.\start-server.cmd
```

Open **http://127.0.0.1:8000/**. The launcher rebuilds the frontend and starts
`campus_routing.integrated:app`, including the mounted Data API. Use `--memory`
for temporary local storage or `--demo` for the original sample experience.
The normal launcher prefers the expanded outdoor graph, uses the residence
building catalog, and enables locally generated drawing maps and portal records.

Run `.\scrape-all.cmd --rules-only` to collect source families and rebuild
supported derivatives. See [the scraper guide](UNIFIED_SCRAPER.md) for selected
stages and [the README](../README.md) for publication to the shared Data API.
Starting the server alone does not refresh or publish scraper data.

Authenticated plans, browser sessions, and generated private drawing maps stay
under ignored `data/private/`; they are not shipped in Git. Run collection in an
authorized local environment to enable those pilots. The older
`start-indoor-pilots.cmd` is a separate Role 1 diagnostic server on port 8004;
use `start-server.cmd` for the full shared application.

For separate Vite development, the configured proxy also forwards `/journey`
and `/plan-wayfinding`. Separate routing/data/indoor base URLs remain supported.

### Vercel deployment configuration

For exact dashboard settings and the `Command "None" exited with 127` fix, see
[the backend Vercel guide](VERCEL_BACKEND.md). Root `vercel.json` explicitly selects
FastAPI and uses JSON `null` for the build command and output directory to retain
framework defaults. Empty strings skip framework building and must not be used.

Root `pyproject.toml` now selects `campus_routing.integrated:app`, so the same
backend Vercel project serves the Data API, outdoor routing, and available indoor
navigation. The Data API remains mounted at `/api/data`. The committed residence
graph and building catalog are selected by default; existing path environment
overrides still work. Root `requirements.txt` supplies runtime dependencies.

Deploy the frontend as a second Vercel project rooted at `frontend`. Set
`VITE_API_BASE_URL`, `VITE_ROUTING_API_URL`, and `VITE_INDOOR_API_URL` to the same
backend domain. Set `VITE_ROUTING_ENGINE=remote`; remove `VITE_CAMPUSNAV_INTEGRATED`
and `VITE_CAMPUSNAV_DEMO` if they were set to `1`. Redeploy the frontend after
setting these build-time URLs. Only two projects are needed for this arrangement.

The outer routing application inherits `CORS_ORIGINS` from the shared Data API,
defaulting to `*` in the combined service. Set it to the frontend origin to
restrict access. `ROUTING_CORS_ORIGINS`, if set, takes precedence. Allowed methods
and headers cover routing, report resolution, and authenticated Data API requests.

The local checks validate both application entrypoints and the frontend build;
they do not constitute a successful hosted Vercel deployment.

## Directions and elevator approaches

Outdoor directions have a separate card on the map, outside the scrolling trip
planner. On phones the planner is shorter while a route is active so the card
stays visible above it. Back / Next focuses each maneuver's location on the map;
the current instruction can also be read aloud. Progress is manual.

The router now splits the selected polylines at supported changes in direction,
including turns within a single unnamed path. Optional `properties.maneuvers`
contains each turn's type, location, leg distance, geometry, and grade. The legacy
`properties.directions` string array remains available with the same instructions.
Sub-meter cartographic zigzags are filtered with a short approach/departure check.
Directions do not invent crossings, indoor paths, or road names.

Indoor directions use the backend's instructions and path. They include walking
from the selected entrance to the named elevator, riding it to the required
floor, and walking from that landing to the destination. For example, ILC south
entrance to N211 includes a corridor approach and relative turn toward the east
elevator before the ride. The backend derives relative turns only from explicitly
mapped image-plan geometry with a known incoming direction. Source-authored
maneuvers take precedence. Missing corridors are not guessed.

The indoor view keeps its visible current-step panel and optional spoken
instructions. Source-based maps use 2D manual progression; indoor GPS and synthetic
3D views are not offered for these plans. Sample 3D navigation remains available
in explicit demo mode and the separate `/indoor.html` sample.

## Automatic entrance handoff

`POST /plan` may return `indoor_arrival`, joined through declared entrance IDs or
an exact shared outdoor OSM anchor. The selected route must actually reach that
anchor. The UI carries its node, portal ID, and label into the indoor modal.
The `/navigation/plan` flow also retains its exact portal and rechecks shared
closures on `/navigation/arrive` when the user continues inside.

Known arrivals do not require choosing the entrance again. An unknown or ambiguous
join requires a current mapped landmark; no nearest door is silently assumed.
This identifies the planned arrival point, not the user's measured indoor position.

## Complete indoor/outdoor journeys

The optional indoor-start search supports a floor, room, or shared-hall landmark.
Source-based endpoints use `/journey`; its ordered itinerary includes indoor
approaches, entrance transitions, and the outdoor portion. Each indoor leg has a
**View this floor route** control. Swapping a trip also swaps indoor selections.

Drawing routes require acceptance of their limits; residence routes require
permission/keycard confirmation. Unknown drawing distances remain `null`, and
the UI identifies the outdoor distance as a partial total.

North D has a source-matched southwest outdoor threshold. Old Chapel and Goodell
have scoped indoor drawing routes, but their outdoor joins remain unresolved;
requests needing those joins fail explicitly. See [drawing journeys](DRAWING_JOURNEYS.md)
and [additional pilots](ADDITIONAL_INDOOR_PILOTS.md) for exact sources and coverage.

Live routing uses the Data API's authoritative active feed, including drawing
routes. Browser simulations are separate request additions. A changed outage
refreshes an active indoor route from its current instruction landmark. Source
status and public reports awaiting review are visible in the planner; unreviewed
social posts do not become automatic closures.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run test:integration
npm.cmd --prefix frontend run build
```

Tests cover ILC entrance/elevator/classroom instructions, exact arrival handoff,
preservation of backend instructions in the floor view, shared outage handling,
unknown drawing distance, consent, existing report endpoints, and source-only behavior
when a backend is unavailable. Floor-plan and facilities gaps remain documented; successful routing
is not a physical-accessibility certification.
