# CampusNav

Step-free campus route planner for UMass Amherst that knows what is broken today: elevator outages,
construction and blocked ramps. Routing is plain graph search (no LLM). Gemini only rewrites directions
in the background and never sits on the critical path.

```
CampusNav/
├── docs/contracts.md   # request/response + closure schema shared by all roles
├── routing/            # Role 1: routing engine (this README section)
├── frontend/           # Role 2
├── services/           # Role 3: MongoDB Atlas + Gemini
└── .env.example
```

## Routing engine (Role 1)

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
uvicorn app.main:app --reload --port 8000
```

`GET /health`, `POST /route` (see `docs/contracts.md`), Swagger UI at `/docs`.

**With the map UI:** the backend also defaults to port 8000, so run routing on 8001 and point the
frontend at it. The frontend calls `POST /api/route`, which this engine serves.

```powershell
uvicorn app.main:app --port 8001                       # in routing/
# frontend .env (role-2-map-ui):
#   VITE_ROUTING_API_URL=http://localhost:8001
#   VITE_ROUTING_ENGINE=remote    # call this engine even when the backend (port 8000) is down
```

In the default `auto` mode the frontend only calls this engine while the backend is reachable.
In both modes, if a response is missing or unusable (including "no route found"), it falls back to
its in-browser router.

```powershell
curl.exe -X POST localhost:8000/route -H "Content-Type: application/json" -d "@mocks/sample_request.json"
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
* **Accessible route**: stairs blocked, edges steeper than `max_grade_pct` (default 5%, ADA) blocked,
  grades above 60% of the limit get a rising cost, closures removed.
* Edges under 8 m with a steep computed grade are penalized, not blocked, because DEM noise on short edges
  would otherwise cut the graph.
* Grade comes from USGS NED 10 m elevation (OpenTopoData). Treat it as approximate, and verify key
  slopes on site.
