# Running and understanding the integrated CampusNav app

**Current integration:** see [the updated Role 2 guide](ROLE2_INTEGRATION.md).
It replaces this older frontend handoff: the updated UI now displays backend indoor
routes and automatically uses a matched outdoor-selected entrance. The original
integration notes below describe the earlier outdoor-only UI and branch state.

For the new floor-aware backend and the Role 2 indoor-view handoff, see
[Indoor mapping](INDOOR_MAPPING.md). Real floor-plan references are available; the current
map interface still uses outdoor routes until reviewed indoor topology and the floor view
are added.
The [guided library–ILC API](GUIDED_NAVIGATION.md) also supports starting-location questions,
arrival confirmation and an indoor continuation. These endpoints are a Role 1/Role 3
handoff; this addition includes no frontend changes.

## Start here

From this project folder, run `.\start-server.cmd` and open http://127.0.0.1:8000.
Keep that terminal running. If an older server already uses port 8000, stop that terminal
with Ctrl+C first. Use `/backend` for the simple diagnostic page and `/docs` for raw API tests.

The map starts with Campus Center to Du Bois Library. Change either building or choose a
map pin. Open preferences to set maximum estimated slope, no stairs, or a powered door.
Green is the preference route and the comparison line is the shortest available route with
the same closures. Both are calculated by the Python backend from the real OSM graph.

Click a building to see sourced entrance information. Its entrance selector can pin a
particular doorway; otherwise the router searches eligible entrance pairs. Door access may
be unverified. A route stops on the mapped outdoor network and warns about any gap to the
requested doorway. It does not certify an indoor path, curb cut, or current elevator access.

**Demo → Simulate blocked path** inserts a temporary closure in this browser's request.
For the initial pair it changes the current graph route from 461.26 m to 607.15 m at the
default 5% limit. Clear the simulation to restore the baseline. Other trips may have no
feasible alternative; constraints are never relaxed automatically. No fake report is saved.

The **Report** form is for actual observations. Path/ramp reports need a map pin. Elevator
reports can select an imported elevator location. Reports persist in a local development
store, are shared by clients of this server, and expire after 24 hours unless reconfirmed.
A student restoration report clears community records only. Role 4 can replace this store
with Atlas; this integration does not claim to provide Atlas TTL indexes or production auth.

## Keep the scraper running

In separate terminals:

```powershell
.\refresh-notices.cmd --rules-only --watch
.\refresh-reports.cmd --rules-only --watch
```

Each worker refreshes hourly. The first uses the saved authorized UMass session. If that
expires, run `.\login-notices.cmd` and sign in yourself. The spreadsheet is a fallback after
live scraping and the last complete scrape. The map polls saved closures every 15 seconds;
its source panel shows actual observation dates and upcoming notices. Public-source
complaints are review candidates, not active walking closures.

Omit `--rules-only` for optional Gemini extraction after deterministic rules abstain. Gemini
keys stay in the backend `.env`. Browser route narration is template-based, and routing
never waits for Gemini. Live Gemini access has not been verified by this integration.

## Code map

| File | Responsibility |
| --- | --- |
| `campus_routing/engine.py` | Filters the graph by stairs, slope and closures; Dijkstra search including multiple entrance choices |
| `campus_routing/buildings.py` | Catalog validation, building/entrance selection, preferred and shortest route comparison |
| `campus_routing/api.py` | FastAPI endpoints and serving the built map |
| `scripts/sync_campus_access.py` | Imports public UMass ArcGIS features and cached OSM entrance positions |
| `campus_notices/` | Scraping, deterministic parsing, optional Gemini fallback, cached notices/public reports, local community store |
| `frontend/src/services/api.ts` | Adapts the Python route contract to the teammate's map components; no mock-router fallback |
| `frontend/src/App.tsx` | Building selection, polling, automatic rerouting and the browser-only simulation |
| `DATA_SOURCES.md` | Source URLs, expected fields, limitations, update commands and remaining coverage needs |

## API used by the map

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Loaded graph source, synthetic flag, node/edge counts |
| `GET /buildings` | Real catalog and mapped entrances/elevators |
| `GET /buildings/status` | Import timestamp and source edition |
| `GET /closures` | Active official and community closures |
| `GET /closures/status` | Official source timestamps/fallback state and local community count |
| `GET /notices` | Current plus future mapped official notices |
| `POST /plan` | Building-aware comparison; origin/destination, max_grade, no_stairs, need_automatic_door, closures |
| `POST /route` | Original stateless point-to-point contract, unchanged |
| `GET /indoor/status` | Indoor floor coverage and whether each building is routable |
| `GET /indoor/sources` | Scraped floor/room references and source freshness |
| `GET /indoor/maps/{building_id}` | Floor images and indoor graph data; draft maps are labeled |
| `POST /indoor/route` | Route between mapped nodes in a reviewed building |
| `POST /journey` | Ordered outdoor, entrance and indoor route legs |
| `POST /reports` | Record a real community observation |
| `POST /reports/{id}/confirm` | Renew an active community report's confirmation/expiry |
| `GET /external-reports` | Unexpired public-source review candidates |

`/plan` returns `accessible`, `standard`, selected entrance records, `notes`, and `failure`.
Each successful route is the existing GeoJSON Feature response; a constrained failure is
null with an explanation. `/plan` and `/route` use the closure array supplied by the client,
so integration tests can inject fixtures without changing server data.

## Frontend development and team handoff

The local `frontend/` clone is based on `MishraAsh2007/CampusNav`, branch `role-2-map-ui`,
commit `ca6d0696868c9ea2b8b52778ea40261d62c52e46`. Local changes are on
`integration/live-routing-scraper`; nothing has been pushed. The Python project is outside
that clone, so a frontend-only push would not include the Python backend or data importer.

```powershell
# Keep the Python server running in its own terminal. From frontend/:
npm.cmd ci --ignore-scripts --no-audit --no-fund
npm.cmd run dev
```

Visit http://127.0.0.1:5173 for development. Vite proxies API requests to port 8000. For the
single-port version, run `npm.cmd run build` in `frontend/`, then start the Python server
from the project root. The existing layout and map renderers are retained; the active data
and routing path use live backend responses. Old mock fixtures remain unused references.

No frontend key is required with Leaflet. Tiles require internet; the saved graph and
processed notices can be served offline. Do not commit private sessions, `.env`, raw notice
caches, or community reports. See the frontend `.env.example` for optional map configuration.

Validation commands:

```powershell
# Project root
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check campus_routing campus_notices scripts tests
# frontend/
npm.cmd run test:integration
npm.cmd run build
```

Integration checks cover alternate entrance choice, no constraint relaxation, unknown door
access, source disagreements, pagination completeness, notice timing, persistence/expiry,
restoration not erasing official data, and frontend failure/cache handling. Browser visual
verification remains outstanding: Computer Use stopped because it could not determine the
current Windows browser URL, before the app could be inspected.
