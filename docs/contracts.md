# Shared contracts

The routing engine is **stateless**: every `/route` call carries the start, end, grade preference and the
current list of closures. Role 3 (Mongo) owns the closure store and passes the active list on each request.

Base URL (local): `http://localhost:8000`. Interactive docs: `/docs`.

## `GET /health`

```json
{ "status": "ok", "graph_loaded": true, "nodes": 2564, "edges": 7288, "graph_path": "..." }
```
`status` is `"degraded"` if the graph failed to load.

## `POST /route`

### Request

```json
{
  "start": { "lat": 42.39076, "lon": -72.52527 },
  "end":   { "lat": 42.39184, "lon": -72.52625 },
  "max_grade_pct": 5.0,
  "avoid_steps": true,
  "include_standard": true,
  "closures": [ /* Closure[] */ ]
}
```

| field | type | default | notes |
|---|---|---|---|
| `start`, `end` | `{lat, lon}` | required | Snapped to the nearest graph node. Must be within the campus bbox (else 422). |
| `max_grade_pct` | number 0-30 | `5.0` | Edges steeper than this are blocked (short edges are only penalized, see below). |
| `avoid_steps` | bool | `true` | `false` lets the accessible route use stairs at a heavy penalty. |
| `include_standard` | bool | `true` | Also return the shortest route that ignores stairs/grade (for the demo comparison). |
| `closures` | `Closure[]` | `[]` | Active problems. Expired ones are ignored and counted in `meta.closures_expired`. |

### Closure

```json
{
  "id": "6553f1...",
  "type": "elevator_out",
  "lat": 42.39177, "lon": -72.52702,
  "radius_m": 25,
  "edge_ids": null,
  "description": "Campus Center elevator out",
  "reported_at": "2026-11-13T21:30:00-05:00",
  "confirmed_at": "2026-11-13T22:05:00-05:00",
  "expires_at": "2026-11-14T06:00:00-05:00"
}
```

| field | type | notes |
|---|---|---|
| `id` | string | Required. Echoed back in `closures_applied`. Use the Mongo `_id` string. |
| `type` | enum | `elevator_out` \| `construction` \| `ramp_blocked` \| `path_closed` |
| `lat`, `lon`, `radius_m` | number | Locate by point (default radius 25 m, max 500). |
| `edge_ids` | `string[]` | Alternative/additional: `"u_v"` OSM node-id pairs, both directions blocked. |
| `reported_at`, `confirmed_at`, `expires_at` | ISO-8601 datetime | Naive datetimes are treated as UTC. `expires_at` null = never. |

At least one of (`lat` + `lon`) or `edge_ids` is required.

What each type blocks:

| type | accessible route | standard route |
|---|---|---|
| `elevator_out` | elevator edges within radius | unaffected (stairs still work) |
| `ramp_blocked` | ramp edges within radius (any edge in radius if no ramp is mapped there) | unaffected |
| `construction` | all edges within radius | all edges within radius |
| `path_closed` | all edges within radius | all edges within radius |

Check `closures_applied[].edges_blocked`: **0 means the closure matched nothing** (for example an
`elevator_out` where no elevator link exists in `data/ground_truth.json`).

### Response

```json
{
  "accessible": { /* RouteResult */ },
  "standard":   { /* RouteResult | null */ },
  "meta": {
    "compute_ms": 3.2, "graph_nodes": 2564, "graph_edges": 7288, "max_grade_pct": 5.0,
    "closures_received": 2, "closures_active": 1, "closures_expired": 1,
    "start": { "node_id": 1443766504, "lat": 42.3907, "lon": -72.5252, "snap_distance_m": 8.1 },
    "end":   { "node_id": 8393893319, "lat": 42.3918, "lon": -72.5262, "snap_distance_m": 4.0 }
  }
}
```

### RouteResult

```json
{
  "mode": "accessible",
  "found": true,
  "reason": null,
  "distance_m": 368.2,
  "duration_s": 368,
  "max_grade_pct": 5.3,
  "step_count": 0,
  "steps_length_m": 0.0,
  "is_step_free": true,
  "geometry": { "type": "Feature", "properties": {"mode": "accessible"},
                "geometry": { "type": "LineString", "coordinates": [[-72.5252, 42.3907], "..."] } },
  "segments": [ /* Segment[] */ ],
  "closures_applied": [
    { "id": "6553f1...", "type": "ramp_blocked", "edges_blocked": 18,
      "confirmed_at": "2026-11-13T22:05:00-05:00", "expires_at": null, "description": "..." }
  ],
  "last_confirmed_at": "2026-11-13T22:05:00-05:00"
}
```

* Coordinates are GeoJSON order: **`[lon, lat]`**.
* `found: false` -> `reason` explains why; `geometry` is null and `segments` is empty. Show `reason` to the user.
* `last_confirmed_at` is the newest `confirmed_at` (falls back to `reported_at`) among closures that blocked
  at least one edge for this route. Use it for "last confirmed X hours ago". Null if nothing is blocking.
* `step_count` only counts steps OSM has tagged (`step_count`); use `steps_length_m` / `is_step_free` as the reliable signals.
* `max_grade_pct` ignores stair edges. It can slightly exceed the requested limit because edges shorter than 8 m are penalized rather than blocked (elevation data is too coarse to trust on them).

### Segment

Consecutive edges with the same kind/name and no turn over 30 degrees are merged.

```json
{
  "edge_ids": ["8393893333_3151897215"],
  "kind": "path",
  "name": null,
  "length_m": 148.6,
  "grade_pct": 3.1,
  "max_grade_pct": 3.4,
  "step_count": null,
  "bearing_deg": 41,
  "instruction": "Turn right for 490 ft, about 3% grade",
  "geometry": { "type": "LineString", "coordinates": [[-72.5254, 42.3912], "..."] }
}
```

* `kind`: `path` | `steps` | `ramp` | `elevator` | `crossing`. Color `steps` red on the map.
* `grade_pct` is signed (+ uphill in travel direction); `max_grade_pct` is absolute.
* `instruction` is template text, instant and deterministic. Role 3 can pass it to Gemini to rephrase; cache by
  `edge_ids`, and fall back to this string after ~2 s.

### Errors

| status | when |
|---|---|
| 422 | invalid body (bad lat/lon, grade out of range, closure without a location) or start/end outside the campus area |
| 503 | graph not loaded (run `python scripts/build_graph.py`) |
