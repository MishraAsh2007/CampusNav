# CampusNav: routing, maps and live disruption sources (Go here: umass-nav.us, and go from Dubois to ILC for test)

Expanded indoor pilots: [Oak, Campus Center and Student Union](docs/EXPANDED_INDOOR_PILOTS.md).
Run `start-indoor-pilots.cmd` for their source-based wayfinding API on port 8004.

For the new Honors College shared-hall pilot, run `start-oak-pilot.cmd` and read
[Oak elevator wayfinding](docs/OAK_HONORS_PILOT.md). This is a private, opt-in drawing-based
backend pilot with explicit outage handling; it does not claim verified physical access.

The expanded residence outdoor configuration is available through `start-residences.cmd`.
Read [all-residence route verification](docs/ALL_RESIDENCE_ROUTES.md) for its 51-building
catalog, sourced-door versus outdoor-meeting-point distinctions, and remaining indoor gaps.

CampusNav is a UMass Amherst walking-route planner. It combines a saved walking graph,
stairs/slope preferences, mapped building entrances and reported disruptions to calculate
routes. This branch packages the current Role 1 routing and Role 3 ingestion work alongside
the existing map UI. The Role 4 data service remains in `backend/`.

**Indoor coverage is a pilot.** ILC uses routes traced on the public UMass plans for
floors 1–2, with a detailed map by default, optional simple/original views and four elevator assets. The former ILC
approximate graph is withdrawn. Du Bois has approximate connections that still
need physical verification. Dorm drawings are acquired
through authenticated SharePoint; Oak has a separate drawing-based wayfinding pilot with
documented gaps. Do not interpret a
successful route calculation or a map's `reviewed` status as facilities certification.
See [ILC coverage, sources and entrance handoff](docs/ILC_PLAN_NAVIGATION.md) and
[phone testing](docs/PHONE_TESTING.md) for the current navigation workflow.
The [ash/indoor-directions merge comparison](docs/ASH_INDOOR_DIRECTIONS_MERGE.md)
describes the added spoken outdoor guide, optional GPS advancement and off-route prompt.

## Run the integrated local map

Use Python 3.11+ and Node.js/npm. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[pipeline,scraper,data,dev,build]"
npm.cmd --prefix frontend ci
.\start-server.cmd
```

Open **http://127.0.0.1:8000**. Keep the server terminal running. The launcher builds
and serves `frontend/`, the Python routing API, and the Data API on one origin.
It reads `backend/.env` when present. `start-server.cmd --memory` runs with temporary data
even when Atlas is configured. Run `start-server.cmd --demo` to reproduce the Role 2 screenshots
with the original browser router, five sample issues, and the sample 2D and 3D floor plans.
In normal live mode, plan Student Union → Integrative Learning Center and choose
**Go inside**. The matched southwest doorway supplies the floor-2 starting point;
choose N211 for a same-floor route or N111/N155 for a route using an elevator.
The direct `/?indoor=ilc` shortcut asks for a starting landmark because it skips
the outdoor arrival. Floors 3–4 are not covered by the live ILC pilot.

The integrated launcher connects the map to the API on port 8000. When running Vite separately,
the map checks which routing endpoints are available before sending a trip. A standalone Data API
can supply its closure feed and building catalog. Live routes require the source-backed Python router;
the browser router and sample indoor layouts are restricted to explicit demo mode. To enable live routing,
run the integrated launcher and stop any older server occupying port 8000.

- Map: http://127.0.0.1:8000/
- API documentation and request testing: http://127.0.0.1:8000/docs
- Data API documentation: http://127.0.0.1:8000/api/data/docs
- Backend diagnostic page: http://127.0.0.1:8000/backend
- Graph health: http://127.0.0.1:8000/health

The saved real outdoor graph is included: 6,885 nodes and 15,618 directed edges.
Starting the app does not download a new walking network or start background scrapers.

The integrated map and routing engine share the Data API's active closures. Official coverage
is shown as unavailable until a scrape is published. In memory mode publication lasts until
the server stops. The map refreshes closures and scheduled notices when it opens, when you
return to its tab, after a report is submitted, and when you open the indoor arrival dialog.
The Python router checks active closures when planning routes and confirming indoor arrival.

## How routing works

The latest routing/scraper additions are integrated with the main Data API and Role 2 UI.
Directions appear in a card beside the map on laptops and a collapsible bottom
panel on phones, with a visible current instruction and Back / Next controls.
Advancing outdoor steps moves a selected-step marker while preserving the route
line and zoom. It does not represent live GPS. Indoor instructions include the corridor approach to the named
elevator, the ride, and the approach from the elevator to the destination. ILC floor-plan
turns come from the mapped path, while missing connections remain explicit gaps.

You can select an **indoor starting place** for a combined indoor/outdoor journey.
North D has an explicit source-matched outdoor threshold. Old Chapel and Goodell have
scoped indoor drawing pilots, but their outdoor joins remain unresolved. Drawing routes
are enabled by default in the UI, with their source/access limitations available
in the guide; residence routes still require permission/keycard confirmation.
Authenticated source plans and generated private pilot data stay out of Git;
collect them locally with the [unified scraper](docs/UNIFIED_SCRAPER.md).
See [the current UI integration](docs/ROLE2_INTEGRATION.md) and
[pilot coverage and sources](docs/ADDITIONAL_INDOOR_PILOTS.md).

1. Outdoor paths from OpenStreetMap become a NetworkX graph. Nodes represent places and
   edges represent paths. Terrain elevation supplies estimated grades during graph preparation.
2. A request supplies endpoints, preferences and active closures. The router filters stairs,
   excessive grades and other constraints, blocks closed edges, and penalizes degraded edges.
3. Dijkstra's algorithm selects the lowest-cost remaining path. The result contains geometry,
   distance, grade estimates, directions and warnings. Gemini does not select the route.
4. Building-aware routing compares feasible entrance approaches. The outdoor graph does not
   imply an indoor connection or a verified path across the final entrance gap.
5. Indoor graphs explicitly connect corridors, doors and elevator stops. Reviewed portals
   bind those graphs to exact outdoor graph nodes. Floor-plan images alone cannot route.

In the trip planner's destination search, enter a room or a building and room (for
example, `ILC N211`). Follow the outdoor route to the selected entrance, then tap
**Go inside** and open the floor-plan guide. Choosing the
indoor view confirms arrival and refreshes closures before calculating the indoor route.
Buildings without source-based indoor coverage remain unavailable in live mode.
Labeled sample layouts are restricted to the explicit demo experience.
The indoor map supports drag/pinch zoom, floor switching and a collapsible
directions card. Next/Back speak the new instruction when the voice toggle is on.
Distances are displayed in feet/miles; API measurements remain in meters.

## Where the web scraper is

**The scraper implementation is `campus_notices/`; runnable workers are in `scripts/`.**

Run **`.\scrape-all.cmd --rules-only`** to collect all source families together.
It creates `data/collected_data.json`, a per-source `data/scrape_status.json`, and
an ignored private bundle. Use `--offline` to combine existing data without fetching.
See the [unified scraper guide](docs/UNIFIED_SCRAPER.md) for source coverage and fallback behavior.

Run `.\refresh-scrapers.cmd --rules-only` for just official notices and public reports.
The public worker uses Reddit's public feed when no Reddit API token is configured.
Public reports stay in the review queue and cannot close routes.

| Source/work | Implementation | Run from the repository root |
| --- | --- | --- |
| Official UMass service interruptions | `campus_notices/sharepoint.py`, `sources.py`, `pipeline.py` | `.\refresh-notices.cmd --rules-only` |
| Deterministic parsing and optional Gemini fallback | `campus_notices/rules.py`, `gemini.py`, `pipeline.py` | Rules run first; omit `--rules-only` to permit configured fallback |
| Public transit, news and social reports | `campus_notices/reports.py` and source adapters | `.\refresh-reports.cmd --rules-only` |
| Public indoor floor references and room directories | `campus_notices/indoor_sources.py`, `indoor_arcgis.py` | `.\refresh-indoor.cmd` |
| Authenticated residence-plan PDFs | `campus_notices/residence_plans.py` | `.\.venv\Scripts\python.exe -m scripts.refresh_residence_plans` |
| All-dorm drawing/review preparation | `campus_notices/residence_workspace.py` | `.\.venv\Scripts\python.exe -m scripts.prepare_all_residences` |

For the official SharePoint notices, install the browser runtime once:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\login-notices.cmd
.\refresh-scrapers.cmd --rules-only
```

Complete UMass sign-in/MFA yourself in the helper's browser and follow the terminal prompts.
The helper stores a local session under ignored `data/private/`. Each teammate/operator
must use their own authorized session; do not distribute session files or passwords.

Run the unified collector hourly in one terminal:

```powershell
.\scrape-all.cmd --rules-only --watch
```

Use `.\refresh-scrapers.cmd --demo` to exercise both pipelines offline with synthetic
data. It writes separate demo snapshots that the live map does not read.

The normal official source is the authenticated scraper. A previously downloaded spreadsheet
is a last-resort fallback, not a required shared asset. A failed scrape preserves prior
source data and freshness metadata. Gemini is optional and stays off the routing request path.
For Gemini, set `GEMINI_API_KEY` in your local ignored `.env`; see `.env.example` and
[the pipeline guide](docs/ROLE3.md). No credentials are included in this branch.

Residence PDF downloads and tracing outputs also remain private. A fresh clone will not
contain those drawings; rerun the authenticated importer with permission to the source folder.

## Data sources and current limits

| Source | Contribution |
| --- | --- |
| OpenStreetMap / Overpass | Outdoor walking paths and available access/stair tags |
| Open Topo Data terrain elevations | Estimated outdoor grades; not measured sidewalk/ramp slopes |
| UMass ArcGIS accessibility layers | Building/entrance/elevator/restroom positions and access attributes; accessibility-map edition August 2022 |
| UMass SharePoint interruption notices | Official outage descriptions and scheduled times |
| Library StackMap and service directory | Floor-image references and service-to-floor associations |
| ILC classroom directory and public floor layers | Classroom references; floor-plan assets for floors 1 and 2 |
| PVTA/news sources | Candidates for review; not automatic proof that a walking path is closed |
| Direct community reports | Observed disruptions with timestamps and expiry |

Public indoor reference collection contains 155 records across six sources. Residence
inventory contains 218 PDFs in 56 folders, grouped into 51 distinct building workspaces.
Counts describe the local source snapshot and can change after refreshes.

Current indoor audit:

- ILC: 21 destination approaches on floors 1–2, with 70 landmarks, 72 connections
  and four independently closable elevators. The southwest outdoor threshold
  joins floor 2. The north entrance has no established outdoor join. Closing all
  four elevators blocks cross-floor routes. Floors 3–4 and untraced rooms remain
  unavailable; physical door widths, corridor grades and current access are unverified.
- Du Bois: all 27 mapped service destinations route from an entrance and back. Third-floor
  plan is missing; E/LL floor-label correspondence and actual door/corridor geometry need
  verification. One modeled elevator asset does not represent verified independent banks.
- Brown and other dorms: private drafts/workspaces await doorway, distance, elevator-stop,
  entrance and resident-access review. Automatic unsupported Brown connections are disabled.

See [exact missing evidence](docs/INDOOR_DATA_NEEDED.md),
[floor coverage](docs/INDOOR_COVERAGE_AUDIT.md) and
[residence work](docs/RESIDENCE_NAVIGATION.md).

## APIs and the separate Role 4 service

| Routing API | Purpose |
| --- | --- |
| `POST /route` | Outdoor point-to-point route |
| `POST /plan` | Building/entrance-aware outdoor route and comparison |
| `GET /closures`, `/closures/status` | Current local merged disruptions and freshness |
| `GET /indoor/status`, `/indoor/maps/{building_id}` | Map coverage and floor-aware graph data |
| `POST /indoor/route`, `/journey` | Indoor-only or combined indoor/outdoor journey |
| `GET /navigation/catalog` | Available mapped buildings, floors and landmarks |
| `POST /navigation/resolve`, `/navigation/plan`, `/navigation/arrive` | Clarify location, plan travel, confirm arrival and continue indoors |

The integrated Data API uses the deployed MongoDB collections and validators. Startup checks
those collections and the existing community report TTL index using read-only operations.
After scraping, preview and publish using the configured server-side admin key:

```powershell
.\.venv\Scripts\python.exe -m scripts.post_scraped_data
.\.venv\Scripts\python.exe -m scripts.post_scraped_data --apply
```

See the [Data API guide](backend/BACKEND.md) for document shapes and standalone testing.

## Tests and offline examples

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check campus_routing campus_notices scripts tests
node --test frontend/tests/live-api.test.mjs
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m scripts.demo_navigation
.\.venv\Scripts\python.exe -m scripts.audit_indoor_coverage
```

The guided demonstration uses fictional layouts under `examples/`; it does not publish
synthetic campus geometry. The current Python suite contains 204 passing tests. Passing
tests demonstrate modeled behavior, not physical accessibility verification.

## Project layout and further reading

| Path | Contents |
| --- | --- |
| `campus_routing/` | FastAPI, outdoor/indoor graph search, entrance selection and guided flow |
| `campus_notices/` | Scraping, rules/Gemini extraction, caching, reports and source preparation |
| `scripts/` | Refresh, graph build, map import, demonstration and audit commands |
| `frontend/` | Existing React/Vite map UI snapshot with its current local API adapter |
| `backend/` | Existing Role 4 data API and MongoDB schema tools |
| `contracts/` | JSON schemas generated from routing models |
| `data/` | Public source catalog, walking graph and pilot maps |
| `data/private/` | Ignored sessions, private PDFs and operator-specific data; not shipped |
| `docs/` | Architecture, source inventory, integration and coverage findings |
| `tests/`, `examples/` | Backend checks and explicitly synthetic protocol examples |

- [Full application guide](docs/APPLICATION_GUIDE.md)
- [All sources and expected output](DATA_SOURCES.md)
- [Scraper operation and fallbacks](docs/ROLE3.md)
- [Indoor contracts and mapping](docs/INDOOR_MAPPING.md)
- [Guided navigation requests](docs/GUIDED_NAVIGATION.md)

Some detailed guides describe the original developer workspace and its historical snapshots.
Use this README for the branch's clean-clone setup and the latest coverage audit for current limits.

## Second routing engine: `routing/` (Role 1, port 8001)
Ash_ver is merged locally alongside the current application. See
[what was integrated and what still differs](docs/ASH_VER_MERGE.md). Its reviewed
ILC additions are used by the default app; the alternate outdoor engine is a
separate comparison tool and does not replace the production `/plan` endpoint.

This is a separate engine from `campus_routing/` above: it has its own graph, 1 m lidar grades, the
`/api/route` and `/api/indoor-route` endpoints, elevator car-count rules and a SIN parser in
`services/scraper/`. Contracts are in `docs/contracts.md`.


OSMnx + NetworkX graph of central campus, USGS elevation for per-edge grade, A* search behind a stateless
FastAPI `/route` endpoint. Closures arrive in each request body, so the engine needs no database.

### Setup

```powershell
cd routing
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Build the graph (once)

`data/graph.graphml` is committed, so teammates can skip this. To rebuild (needs internet, about 1 minute;
elevations are cached in `data/elevation_cache.json`):

```powershell
python scripts/build_graph.py
```

Edit `data/ground_truth.json` (verified elevators, ramps, entrances; schema in `app/graph/overrides.py`)
and rebuild to fold it in.

### Demo: standard vs. accessible

```powershell
python scripts/demo_route.py                                   # ILC -> Campus Center
python scripts/demo_route.py --closures mocks/closures.json    # ramp blocked: accessible route reroutes
python scripts/demo_route.py --max-grade 8 --geojson out.geojson
python scripts/demo_route.py --request mocks/sample_request_destination.json   # route to a building's best entrance
```

Routing to a building (`destination` instead of `end`) checks elevator closures and entrance
accessibility first, picks the entrance that suits the indoor leg, and returns plain-language
warnings. See `docs/contracts.md`. The entrances in `mocks/sample_request_destination.json`
are placeholders.

### Run the API

```powershell
uvicorn app.main:app --reload --port 8001
```

`GET /health`, `POST /route` (see `docs/contracts.md`), Swagger UI at `/docs`.

The backend and integrated Python server use port 8000. Keep this standalone
engine on 8001 and inspect `/docs` there for comparisons. The current frontend
requires the integrated source-routing/portal contracts; changing its API URL
to this engine is not a supported way to retain all current features. Live mode
does not fall back to the sample browser router.

```powershell
curl.exe -X POST localhost:8001/route -H "Content-Type: application/json" -d "@mocks/sample_request.json"
```

### Tests

```powershell
python -m pytest -q
```

### How it works

| piece | file |
|---|---|
| Edge cost: stairs, grade, ground truth | `app/routing/weights.py` |
| Closures -> blocked edges, expiry | `app/routing/closures.py` |
| A* / Dijkstra | `app/routing/pathfinding.py` |
| Path -> GeoJSON + template directions | `app/routing/serialize.py` |
| OSM download, edge classification | `app/graph/build.py` |
| Elevation + grade | `app/graph/elevation.py` |
| Ground-truth overrides | `app/graph/overrides.py` |

* **Standard route**: shortest distance, stairs and slope ignored.
* **Accessible route**: stairs blocked, longer edges steeper than `max_grade_pct` (default 5%) blocked,
  grades above 60% of the limit get a rising cost, closures removed.
* Edges under 8 m with a steep computed grade are penalized, not blocked, because DEM noise on short edges
  would otherwise cut the graph.
* The default collector uses USGS EPQS/3DEP; OpenTopoData and Open-Meteo adapters
  remain available. Treat terrain grades as estimates. The committed graph also
  contains deck assumptions and an unverified sample-based ramp override; see the
  merge comparison before using it as the production source.
