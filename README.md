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

Open a terminal in VS Code (**Terminal → New Terminal**). It starts in the project folder.

### Laptop

```powershell
npm run dev
```

Open http://localhost:5173/. Stop the server with `Ctrl + C`.

Run `npm install` first if you haven't yet, or if you pulled teammates' changes that add packages.

### Phone

1. Connect the phone to the same Wi-Fi as the laptop.
2. On the laptop, run:
   ```powershell
   npm run dev:phone
   ```
3. Open the `Network:` address that starts with `172.30.` on the phone, for example `https://172.30.231.238:5173/`. Skip the `192.168.56.1` one.
4. Accept the certificate warning:
   - **Android:** Advanced → Proceed.
   - **iPhone:** Show Details → visit this website.

If the page won't load on the phone, allow Node.js through Windows Firewall, or set your Wi-Fi network to Private.

### Indoor shortcut

Add `?indoor=ilc` to the address, for example `http://localhost:5173/?indoor=ilc`. It goes straight to the ILC room picker. `?indoor=dubois-library`, `?indoor=student-union` and `?indoor=campus-center` work too.

Backend (optional, second terminal; full details in [backend/BACKEND.md](backend/BACKEND.md)):

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload    # http://127.0.0.1:8000
```

The frontend finds the backend at `VITE_API_BASE_URL` (default `http://localhost:8000`), polls `GET /closures`, sends reports to `POST /reports`, and taps "Still a problem" to `POST /reports/{id}/confirm`. When the backend is off, the same features run from an in-browser store.

Routing engine (optional, third terminal; Role 1's `routing/` folder on the `Ash_ver` branch):
```powershell
uvicorn app.main:app --port 8001      # run inside routing/
```
Add this to `.env` (already in `.env.example`), then restart `npm run dev`:
```
VITE_ROUTING_API_URL=http://localhost:8001
```
The frontend checks the engine's `GET /health` every 15 s and sends routes to `POST /api/route`. The route card shows a badge: **Main routing engine** when the engine answered, **In-browser router** when it was unreachable and the app routed locally. If the engine answers "no route", the card says *No step-free route available via Main routing engine* instead of swapping in a local route. The indoor directions start at the entrance the engine picked.

The frontend works with no keys and no backend. Optional `.env` keys (see `.env.example`):

- `VITE_GOOGLE_MAPS_API_KEY`: Google basemap, plus Google's wheelchair-entrance data in building sheets (enable *Maps JavaScript API* and *Places API (New)*). Without it, or if Google rejects the key, the app uses OpenStreetMap tiles.
- `VITE_GEMINI_API_KEY`: Gemini route summaries (default model `gemini-3.8-flash`; 2.0 Flash has been shut down).
- `VITE_ROUTING_ENGINE=local`: force the in-browser router during a live demo.
- `VITE_INDOOR_API_URL`: optional live indoor maps from the campus_routing server (`GET /indoor/status`, `GET /indoor/maps/{id}`).
- `VITE_INDOOR_SAMPLES`: `fallback` (default), `prefer` or `off` for the built-in sample floor plans.

## Adding a building (dorms included): no frontend change

**Outdoor (map pin, routing to its doors):** add the building to the Role 4 backend (`POST /buildings` with `id`, `name`, `lat`, `lng`, `entrances[]`). The app reads `GET /buildings` and shows it on the next load. Routing to buildings outside central campus needs the main routing engine; the in-browser fallback graph only covers central campus and says so instead of guessing.

**Indoor (floor plans, room search, turn-by-turn, 2D/3D):** add one map file in the team's IndoorMap v1 format (`contracts/indoor-map.schema.json` on the `routing-scraper` branch) to `data/indoor/<building_id>.json`, or serve it from the indoor API. The app:
- matches it to the outdoor building by `building_id`, then by name, then by position (so `library` matches `dubois-library`);
- adds it as a destination by itself if the backend doesn't have the building yet (location and doors from entrances with `position`);
- builds the room search from `nodes` of kind `room` (`label` and `aliases`) and the floor picker from `floors` (order from the floor `level`, or parsed from labels like "Lower Level" or "3rd Floor");
- routes step-free over `edges` (no `steps`, nothing marked `step_free: false` or not public), avoids elevators that closures mark out of service (`asset_id`), and prefers automatic doors;
- shows `image_url` when it is an image in the floor's pixel space, else draws a schematic from the corridors and rooms;
- places GPS from the floor's `bounds` (`{ topLeft, bottomRight }` lat/lng of the image, optional) or from entrances and elevators that have coordinates.

Maps with no entrance or no rooms and corridors (like the current Campus Center draft) are skipped, and the built-in sample is used if there is one. A `draft` map that can be routed is used, with a "Draft indoor map" note.

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

- **Backend (`backend/main.py`)**: no changes needed. The frontend reads its closure shape as-is. `POST /reports` only takes `{lat, lng, type, radius}`, so the frontend keeps the report's title and `connector_id` locally, and elevator closures snap to the nearest elevator within 30 m. Two things the backend doesn't have yet and the frontend handles in the browser: `automatic_door` reports, and marking a closure fixed.
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
