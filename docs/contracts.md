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

### Destination building (look-ahead)

Instead of `end`, a request can name a destination building. The engine then picks the
entrance that suits the indoor leg, and both routes end at that entrance. Send exactly one of
`end` or `destination` (422 if neither).

```json
{
  "start": { "lat": 42.38970, "lon": -72.52790 },
  "destination": {
    "needs_elevator": true,
    "room": "ILC S331",
    "building": { /* one item from the backend's GET /buildings, as-is */ }
  },
  "closures": [ /* items from GET /closures, as-is */ ]
}
```

| field | notes |
|---|---|
| `destination.building` | Backend `/buildings` shape: `id`, `name`, `lat`, `lng`, `entrances[]` (`name`, `lat`, `lng`, `step_free`, `hasAutoDoorOpener`, `isAccessibleToAllFloors`, `IsKeyCardRequired`), `elevator_count`, `elevators[]` (`location`, optional `lat`/`lng`). `lon` is accepted for `lng`. |
| `destination.needs_elevator` | `true` if the room is on a floor only reachable by elevator. The frontend decides this until the indoor stage exists. |
| `destination.room` | Optional, echoed back. |

How the entrance is chosen:
1. **Unusable** entrances: not `step_free`, within the radius of an active non-elevator closure,
   or no step-free route under the grade limit.
2. **Elevator status**: an active `elevator_out` closure counts against an elevator within
   `radius_m + 10 m` of its coordinates. If the elevators have no coordinates, a closure within
   60 m of the building center marks **all** of them as possibly out (conservative, same policy as
   "may be unavailable" notices).
3. **Ranking** among usable entrances: no key card first, then (if `needs_elevator`) entrances
   not marked `isAccessibleToAllFloors: false`, then lowest outdoor route cost plus the
   straight-line distance from the door to the nearest working elevator.

The response gets a `destination` object (null when `end` was used):

```json
"destination": {
  "building_id": "integrative-learning-center",
  "building_name": "Integrative Learning Center",
  "room": "ILC S331",
  "needs_elevator": true,
  "upper_floors_reachable": true,
  "entrance": { /* the chosen EntranceOption */ },
  "entrances": [
    {
      "name": "South entrance", "lat": 42.39065, "lon": -72.5257,
      "step_free": true, "usable": true, "chosen": true, "reasons": [],
      "route_distance_m": 440.4, "to_working_elevator_m": 31.7,
      "auto_door": false, "key_card_required": false, "accessible_to_all_floors": true
    }
  ],
  "elevators": {
    "total": 2, "possibly_out": 1, "working": 1, "located": 2,
    "closure_ids": ["sin-1751-ilc-e188"], "last_confirmed_at": "2026-11-13T22:00:00-05:00"
  },
  "warnings": ["1 of 2 elevator(s) at Integrative Learning Center may be out of service."]
}
```

* Show `warnings` before the user starts walking. They are plain-language strings.
* `upper_floors_reachable: false` means no working elevator. The outdoor route is still given
  (the entrance level is reachable), with a warning.
* No usable entrance: `accessible.found` is false and `entrances[].reasons` explain why. The
  standard route goes to the nearest entrance.
* No entrance data: both routes go to the building center, with a warning.
* `elevators.last_confirmed_at` drives "last confirmed X ago" for elevator problems, which
  don't block outdoor edges and so don't appear in `accessible.last_confirmed_at`.

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

`starts_at` (optional): a closure is not applied before this time and is counted in
`meta.closures_pending`.

**Backend format is accepted as-is.** Items from the backend's `GET /closures`,
`/official-reports` or `/community-reports` can be passed straight into `closures`. They're
translated on input:

| backend | routing |
|---|---|
| `lng` (or `location.lng`) | `lon` |
| `radius` | `radius_m` |
| `type`: `elevator` / `ramp` / `path` / `construction` | `elevator_out` / `ramp_blocked` / `path_closed` / `construction` |
| `start_time` | `starts_at` |
| `end_time` | `expires_at` |
| `last_confirmed` | `confirmed_at` |
| `details` or `title` (if `description` is empty) | `description` |

Other fields (`status`, `source`, `last_updated`, ...) are ignored. If a payload has both
names for a field, the routing name wins.

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
    "closures_received": 2, "closures_active": 1, "closures_expired": 1, "closures_pending": 0,
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

## `POST /api/route` (map UI contract)

Same pathfinding as `/route`, in the request and response shapes the map UI
(`role-2-map-ui`, `src/services/api.ts` and `contracts/route.contract.json`) already uses.

Request: `{start: {lat, lng}, end: {lat, lng}, preferences: UserPreferences, closures: Closure[]}`
(the frontend's own types, sent as-is).

Response: `{step_free: RouteResponse, shortest: RouteResponse, meta}`. Each `RouteResponse` is a
GeoJSON FeatureCollection: one LineString feature per segment (`grade`, `is_step`, `is_ramp`,
`is_elevator`, `step_count`, `segment_name`), plus `summary`, `steps` (with `icon` and `at`),
`profile` (cumulative distance and elevation), and `avoided` (closures routed around). An extra
`found` field is `false` when there's no route, with the reason in `summary.warnings`.

| frontend input | engine behavior |
|---|---|
| `preferences.max_grade_pct` | max grade, clamped to 0–30 |
| `preferences.no_stairs` or `wheelchair_required` | stairs blocked |
| other preferences | not used yet; listed in `meta.ignored_preferences` |
| closure `status: "repaired"` | dropped |
| closure `status: "closed"` or `"degraded"` | blocks (block-by-default policy) |
| closure `type: "automatic_door"` | dropped (affects entrances, not walkways) |
| closure `affects: "road"` | dropped (vehicles only) |
| closure `radius` | clamped to 500 m |
| unreadable closure | skipped, listed in `meta.skipped_closures`; never fails the request |

Start or end outside the campus area returns 422.

### Letting the engine pick the destination entrance

Send `destination` instead of `end`. `building` is the map UI's `Building` object as-is (a
backend `/buildings` item also works):

```json
{
  "start": { "lat": 42.389702, "lng": -72.528172 },
  "destination": { "building": { /* Building */ }, "needs_elevator": true, "room": "S331" },
  "preferences": { /* UserPreferences */ },
  "closures": [ /* all non-repaired Closures, including automatic_door */ ]
}
```

The engine applies the same rules as the UI's `usableEntrances()`, plus live elevator status:
- Entrances that aren't `step_free` are out **only if** the user needs step-free access
  (`no_stairs` or `wheelchair_required`). Entrances inside an active ramp, path or construction
  closure are always out.
- The `shortest` route picks its own entrance: the nearest one not closed to everyone, steps
  allowed, door openers ignored (`destination.standard_entrance_id` / `standard_end`).
- `automatic_door` closures near an entrance add cost (closed +120 m, degraded +40 m). With
  `need_automatic_door`, entrances with a working opener always rank first, and push-button
  doors cost +10 m.
- Elevators: `elevators.list[].status = "out_of_service"`, `working_count`, `status = "all_down"`,
  and active elevator closures near the building all count. If `needs_elevator` and none work,
  the route still goes to the door, with a warning up front.
- Among the rest: the cheapest step-free route from the start.

The response adds `destination` (null when `end` was used):

| field | use |
|---|---|
| `destination.end` | `{lat, lng}` of the chosen entrance. Compare the route's end to this, not to the building. |
| `destination.entrance_id` | the UI's entrance `id` |
| `destination.entrances[]` | every entrance with `usable`, `reasons`, `route_distance_m`, `door_issue` |
| `destination.elevators` | `total`, `working`, `possibly_out`, `closure_ids` |
| `destination.upper_floors_reachable` | false if no elevator works |
| `destination.warnings` | also prepended to `step_free.summary.warnings` |

Each route ends at its own entrance (`end` for `step_free`, `standard_end` for `shortest`), and
the last step reads "Arrive at <building>, <entrance>".

**Frontend change needed** (in `role-2-map-ui`, `planRoutes()` in `src/services/api.ts`):

```ts
const destBuilding = destination.building_id ? buildings.find((x) => x.id === destination.building_id) : undefined;
// request body: replace `end` with
...(destBuilding ? { destination: { building: destBuilding, needs_elevator: false } } : { end: { lat: end.lat, lng: end.lng } }),
// validation: check each route against the entrance the engine chose for it
const endPoint = r.data?.destination?.end ?? end;
const stdEndPoint = r.data?.destination?.standard_end ?? end;
if (r.ok && validRemote(remote, endPoint)) { ... }          // step_free
// shortest: validRemote(r.data.shortest, stdEndPoint)
```

`needs_elevator` stays `false` until the UI knows the room's floor.

### Errors

| status | when |
|---|---|
| 422 | invalid body (bad lat/lon, grade out of range, closure without a location) or start/end outside the campus area |
| 503 | graph not loaded (run `python scripts/build_graph.py`) |
