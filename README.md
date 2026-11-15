# CampusNav: routing, maps and live disruption sources

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

**Indoor coverage is a pilot.** ILC and Du Bois have computable indoor graphs with
approximate connections that still need physical verification. Dorm drawings are acquired
through authenticated SharePoint; Oak has a separate drawing-based wayfinding pilot with
documented gaps. Do not interpret a
successful route calculation or a map's `reviewed` status as facilities certification.

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
Open `/?indoor=ilc` and select **S335 Seminar** to view the indoor example.

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
Directions now appear directly below the trip fields, with a visible current instruction
and Back / Next controls. Indoor instructions include the corridor approach to the named
elevator, the ride, and the approach from the elevator to the destination. ILC floor-plan
turns come from the mapped path, while missing connections remain explicit gaps.

You can select an **indoor starting place** for a combined indoor/outdoor journey.
North D has an explicit source-matched outdoor threshold. Old Chapel and Goodell have
scoped indoor drawing pilots, but their outdoor joins remain unresolved. Drawing routes
require acceptance of their limitations; residence routes also require permission/keycard
confirmation. Authenticated source plans and generated private pilot data stay out of Git;
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
example, `ILC N151`). Follow the outdoor route to the selected entrance, then tap
**Go inside** and choose **2D Floor Plan** or **3D Immersive View**. Choosing the
indoor view confirms arrival and refreshes closures before calculating the indoor route.
Buildings without source-based indoor coverage remain unavailable in live mode.
Labeled sample layouts are restricted to the explicit demo experience.

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
