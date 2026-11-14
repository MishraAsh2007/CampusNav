# CampusNav: routing, maps and live disruption sources

CampusNav is a UMass Amherst walking-route planner. It combines a saved walking graph,
stairs/slope preferences, mapped building entrances and reported disruptions to calculate
routes. This branch packages the current Role 1 routing and Role 3 ingestion work alongside
the existing map UI. The Role 4 data service remains in `backend/`.

**Indoor coverage is a pilot.** ILC and Du Bois have computable indoor graphs with
approximate connections that still need physical verification. Dorm drawings are acquired
through authenticated SharePoint, but dorm routing is not enabled. Do not interpret a
successful route calculation or a map's `reviewed` status as facilities certification.

## Run the integrated local map

Use Python 3.11+ and Node.js/npm. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[pipeline,scraper,dev]"
npm.cmd --prefix frontend ci
.\start-server.cmd
```

Open **http://127.0.0.1:8000**. Keep the server terminal running. The launcher builds
`frontend/dist` if it does not exist and serves it through the Python routing API.
After editing frontend source, rebuild with `npm.cmd --prefix frontend run build`.

- Map: http://127.0.0.1:8000/
- API documentation and request testing: http://127.0.0.1:8000/docs
- Backend diagnostic page: http://127.0.0.1:8000/backend
- Graph health: http://127.0.0.1:8000/health

The saved real outdoor graph is included: 6,885 nodes and 15,618 directed edges.
Starting the app does not download a new walking network or start background scrapers.

Fresh clones have no authenticated notice snapshot. Closure/status endpoints may report
unavailable until a source refresh succeeds. Building routing with an explicit `closures: []`
is useful for isolated API testing, but deliberately excludes all disruptions. The map's
stale/unavailable-source display should be respected; no notices does not establish no outages.

## How routing works

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

The integrated map currently calls the outdoor `/plan` flow. Indoor `/journey` and guided
`/navigation/*` are backend handoffs; this branch does not add a floor-selector interface.

## Where the web scraper is

**The scraper implementation is `campus_notices/`; runnable workers are in `scripts/`.**

| Source/work | Implementation | Run from the repository root |
| --- | --- | --- |
| Official UMass service interruptions | `campus_notices/sharepoint.py`, `sources.py`, `pipeline.py` | `.\refresh-notices.cmd --rules-only` |
| Deterministic parsing and optional Gemini fallback | `campus_notices/rules.py`, `gemini.py`, `pipeline.py` | Rules run first; omit `--rules-only` to permit configured fallback |
| Public transit/news and authorized social adapters | `campus_notices/reports.py` and associated source adapters | `.\refresh-reports.cmd --rules-only` |
| Public indoor floor references and room directories | `campus_notices/indoor_sources.py`, `indoor_arcgis.py` | `.\refresh-indoor.cmd` |
| Authenticated residence-plan PDFs | `campus_notices/residence_plans.py` | `.\.venv\Scripts\python.exe -m scripts.refresh_residence_plans` |
| All-dorm drawing/review preparation | `campus_notices/residence_workspace.py` | `.\.venv\Scripts\python.exe -m scripts.prepare_all_residences` |

For the official SharePoint notices, install the browser runtime once:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\login-notices.cmd
.\refresh-notices.cmd --rules-only
```

Complete UMass sign-in/MFA yourself in the helper's browser and follow the terminal prompts.
The helper stores a local session under ignored `data/private/`. Each teammate/operator
must use their own authorized session; do not distribute session files or passwords.

Run workers hourly in separate terminals:

```powershell
.\refresh-notices.cmd --rules-only --watch
.\refresh-reports.cmd --rules-only --watch
```

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

- ILC: all 16 mapped destinations route from an entrance and back. Floors 3/4 lack plan
  assets; floor 4 has no mapped destination. Closing either modeled elevator preserves all
  destinations; closing both leaves only the seven first-floor destinations reachable.
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

The root Python service currently uses local caches and its development community store.
The separate `backend/` service supports MongoDB Atlas and its own buildings/reports feeds;
it is **not automatically connected** by starting the routing app. See
[backend setup](backend/BACKEND.md) and [contract/integration gaps](docs/BACKEND_HANDOFF.md).
If running both services, use different ports, such as routing `8000` and data service `8001`.
Keep the data-service admin key in its backend environment, never in frontend code.

## Tests and offline examples

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check campus_routing campus_notices scripts tests
npm.cmd --prefix frontend run test:integration
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
