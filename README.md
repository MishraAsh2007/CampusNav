# CampusNav

**Step-free routes across UMass Amherst that change when an elevator, door opener or ramp breaks.**

Google Maps knows where a ramp is. It does not know the Campus Center elevator stopped working at 9 a.m. CampusNav routes on the real campus path network, with the needs you set (wheelchair, crutches, stroller, low vision), and reroutes everyone the moment a student reports an outage.

## Why

Student reporting at UMass describes the gap directly:

- A dorm elevator stayed broken for four weeks while a wheelchair user lived on that floor. Library and ILC automatic doors were out for weeks. ([Daily Collegian, 2023](https://dailycollegian.com/2023/03/umass-campus-is-not-accessible/))
- Plows bury curb cuts; Disability Services said it depends on people telling it where problems are. ([Daily Collegian, 2013](https://dailycollegian.com/2013/02/for-some-winter-weather-burdens-on-campus-handicap-accessibility/))
- Boyden and Totman have inaccessible floors but are common exam rooms. ([Daily Collegian, 2018](https://dailycollegian.com/2018/09/handicap-inaccessible/))

Reddit and Yik Yak were not searchable for this research (Reddit returned 403; Yik Yak has no public web index), so the sources are student journalism and UMass pages.

## What's real

| Data | Source |
| --- | --- |
| 2,347 walkway segments, 44.7 km | OpenStreetMap (Overpass API) |
| 140 staircases, 1,240 steps, handrails, surfaces, kerbs | OpenStreetMap tags |
| Slope at every one of 1,894 intersections | USGS 3DEP 1 m lidar |
| Building outlines and entrance positions | OpenStreetMap |
| Door types, elevator lists, ramp grades | Seed data for the demo (Role 3 replaces it) |
| Elevator connector (Campus Center) | `scripts/curated-connectors.json` |

## Run

Frontend (repo root):

```bash
npm install
npm run dev          # http://localhost:5173
```

Backend (optional, second terminal; full details in [backend/BACKEND.md](backend/BACKEND.md)):

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload    # http://127.0.0.1:8000
```

The frontend uses `VITE_API_BASE_URL` (default `http://localhost:8000`) to fetch `GET /closures` and submit `POST /community-reports`. **Still a problem** calls `POST /community-reports/{id}/confirm`, and **It works now** calls `DELETE /community-reports/{id}` for the selected community report.

The frontend works with no keys and no backend. Optional `.env` keys (see `.env.example`):

- `VITE_GOOGLE_MAPS_API_KEY`: Google basemap, plus Google's wheelchair-entrance data in building sheets (enable *Maps JavaScript API* and *Places API (New)*). Without it, or if Google rejects the key, the app uses OpenStreetMap tiles.
- `VITE_GEMINI_API_KEY`: Gemini route summaries (default model `gemini-3.8-flash`; 2.0 Flash has been shut down).
- `VITE_ROUTING_ENGINE=local`: force the in-browser router during a live demo.
- Buildings and closures are cached in the tab's `sessionStorage`. The app reads the cache on reload and fetches fresh data on opening and every five minutes. A successfully submitted community report is added immediately after the API accepts it. Ending the tab session clears the cache; browser session restoration may restore it.
- With `VITE_ROUTING_ENGINE=auto`, routing runs in the browser until `VITE_ROUTING_API_URL` points to a server implementing `POST /api/route`. The data backend on port 8000 serves buildings and reports.

## Judge demo (60 seconds)

Open `http://localhost:5173/?demo` or press **J**.

1. **Load trip**: Student Union to the Campus Center upper terrace, manual wheelchair. A regular map says 2 min with **27 steps**. CampusNav says 3 min via the concourse elevator.
2. **Break elevator**: POSTs a fake student report to `/reports`, re-fetches `/closures`, and recomputes. The line visibly moves (the old path fades out in grey): **398 m, +267 m, about 4 min longer**, still zero stairs. The log shows each call's latency.
3. **Fix it**: reports the elevator working; the route snaps back.

Then open **Manual wheelchair ▾** to show the needs dropdown, tap a building pin for entrances, elevators and sourced student reports, and tap **Report** to show the two-tap flow.

## Role 2 checklist

| Requirement | Where |
| --- | --- |
| Map canvas | Google Maps (`@vis.gl/react-google-maps`) with Leaflet/OSM fallback, `src/components/map/` |
| Preference panel: max-slope slider, No Stairs toggle | `NeedsMenu.tsx` (plus wheelchair, handrails, surfaces, covered, auto doors, restroom, crossings) |
| Draw GeoJSON route | `scene.ts` draws `RouteResponse.features`; elevator and stairs segments styled separately |
| Interactive entrance status markers | Green / amber / red / grey dots per entrance; tap for details |
| Poll `/closures` | Every 5 s in `App.tsx`; state only updates when the data changes |
| Send closures with start/end to the router | `planRoutes()` POSTs `{start, end, preferences, closures}` to `/api/route`, falls back to the in-browser engine |
| Report Outage / Judge Mode, redraw without refresh | `ReportSheet.tsx`, `JudgePanel.tsx` |

## Scripts

```bash
node scripts/build-campus-graph.mjs   # rebuild public/data/campusGraph.json (cached; --refresh re-downloads OSM)
node scripts/check-demo.mjs           # rehearse the elevator demo in the terminal
node scripts/analyze-graph.mjs        # slope stats, worst stair detours, building pairs
```

## Integration notes for other roles

- **Backend (`backend/main.py`)** supports creating and deleting community reports. See [the backend guide](backend/BACKEND.md) for the payloads. Elevator closures can snap to the nearest elevator within 30 m.
- **Routing (Role 1)**: the frontend POSTs `{start, end, preferences, closures}` to `/api/route` and uses the answer if it's valid; otherwise the in-browser engine (`src/services/routingEngine.ts`) routes on `public/data/campusGraph.json`.
- **Contracts**: `contracts/` adds an optional `connector_id` on reports and closures.
- `roles/` holds the earlier per-role stubs; `backend/` is the real Role 4 service.

## Team layout

```
backend/     Role 4: FastAPI + MongoDB Atlas (see backend/BACKEND.md)
src/         Role 2: map UI
public/data/ campus walkway graph used by the in-browser router
scripts/     graph build + demo checks (scripts/cache keeps OSM + lidar downloads)
contracts/   shared JSON schemas
roles/       earlier stubs for routing, pipeline and backend
```

Map data © OpenStreetMap contributors (ODbL). Elevation: USGS 3DEP (public domain).
