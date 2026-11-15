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
2. **Elevator status**: how many cars a building has comes from `data/indoor_overrides.json` when
   it has an entry (UMass GIS and the map UI hold one marker per lobby, not per car; the ILC has
   3 cars, Du Bois 5), otherwise from the building data. A closure counts when it is within
   `radius_m + 10 m` of a car, or within 60 m of the building center. What it takes out depends
   on its `scope`:
   - `all`: every car (building power shutdown, "all four elevators").
   - `cars` + `cars: [5]`: the named cars (matched by car number).
   - `one`, or no scope: one car. If the closure sits at a lobby with one free car, that car is
     out. Otherwise one car is out and *which* is unknown (`elevators.unattributed_out`); the
     rest stay usable.
   - A building with a single car loses it to any elevator closure.
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
    "closure_ids": ["sin-1751-ilc~one"], "count_source": "override", "out_cars": [], "unattributed_out": 1, "last_confirmed_at": "2026-11-13T22:00:00-05:00"
  },
  "warnings": ["1 of 2 elevator(s) at Integrative Learning Center may be out of service (not known which); the other should still reach upper floors."]
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
| `scope`, `cars` | `"all"` \| `"one"` \| `"cars"`, `int[]` | `elevator_out` only: which cars. Optional; see below. |
| `reported_at`, `confirmed_at`, `expires_at` | ISO-8601 datetime | Naive datetimes are treated as UTC. `expires_at` null = never. |

At least one of (`lat` + `lon`) or `edge_ids` is required.

`starts_at` (optional): a closure is not applied before this time and is counted in
`meta.closures_pending`.

**Scope in the id.** The backend's `OfficialNotice` and the map UI carry only `id`, `title` and
`description`, so scope also travels as an id suffix: `sin-1394-ilc~one`, `sin-813-dubois-library~car5`,
`sin-1049-lincoln-campus-center~car1+2+3+4`, `sin-1458-student-union~all`. The engine reads the
suffix when `scope` isn't set. Community reports have no suffix, so each reads as one car at its
location.

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

### Letting the engine pick the start building's exit

Send `origin: {building, needs_elevator, room}` instead of (or with) `start`, in the same shape
as `destination`. Also accepted by `/route`. Each exit is judged like a destination entrance
(steps only exclude it for step-free users; closures, door-opener issues and
`need_automatic_door` apply the same way; key cards are ignored when leaving). The chosen exit
is the one with the cheapest **whole trip**, including the destination's own entrance choice.
`needs_elevator: true` means the user is on a floor that needs an elevator to reach the exit
level: the door-to-elevator distance is added, and a warning is given if no elevator works.

The response adds `origin` (null when `start` was used): `exit_id`, `start` (`{lat, lng}` of
the chosen exit), `standard_exit_id`, `standard_start`, `exits[]` with reasons, `elevators`,
`can_reach_exit` and `warnings` (also prepended to `step_free.summary.warnings`). The first
step reads "Leave <building> by the <exit>. ...".

**Snapping.** Points are matched to the nearest walking-network junction. For the step-free
route, a point at least 15 m from any path (a building center, GPS fix or map tap) whose nearest
junction is a dead end for this user (only stairs or a too-steep path lead out) is moved to the
nearest usable junction, at most 40 m farther. This only happens when the start and end couldn't
otherwise reach each other. Points on a path or at a door are never moved, so an inaccessible
door still reports "no route". Moved points show `meta.start.moved` / `meta.end.moved` (also in
`/route`), and the step-free route gets a warning such as "Starting from the nearest path you
can use, about 41 m from the point you chose."

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


## `POST /api/indoor-route` (second stage: entrance to room)

Called when the user asks for indoor directions after the outdoor route. Send the entrance the
outdoor route ended at (`destination.end` from `/api/route`) and the same closures.

```jsonc
{
  "building_id": "ilc",                       // id, name or alias (see indoor_overrides.json)
  "building": { ... },                        // optional: the map UI / backend building (elevator flags)
  "entrance": { "lat": 42.390887, "lng": -72.525402 },   // optional: omit to pick the best door
  "room": "N151",                             // or "floor": "5th floor", or "node_id"
  "preferences": { "step_free": true },       // default true
  "closures": [ ... ]                         // same list as /api/route
}
```

**Leaving a building.** Add `"direction": "to_exit"` and pass the door as `"exit": {lat, lng}` (the
start exit `/api/route` chose, or omit for the best door). `room` or `floor` is then where the user
starts, and the response has `exit` in place of `entrance`. The rules below apply the same way.

Every outcome is HTTP 200; check `status`:

| status | meaning |
|---|---|
| `ok` | `entrance`, `destination`, `total_m`, `steps[]` (text), `legs[]` (per floor, with `points` in that floor's coordinates and its `image_url`), `elevators[]`, `warnings[]` |
| `no_route` | `message` says why (for example every elevator bank is out); `elevators[]` shows each bank |
| `not_found` | the room or floor isn't on the map |
| `not_public` | the floor isn't a visitor destination (Du Bois 3rd floor) |
| `no_map` | no indoor map for that building yet (Campus Center is a draft) |

How it works:
- Maps come from `routing/data/indoor/*.json` (the scraper's indoor maps, not committed here). Corrections
  from `routing/data/indoor_overrides.json` apply on top: doors with their real floor, elevator cars,
  non-public floors.
- The given `entrance` is matched to an indoor door within 30 m. If no route exists from it (for
  example it opens onto floor 1 and the room is upstairs with the elevators out), the router
  falls back to the best door and says so in `warnings`.
- Elevators are grouped into banks. A bank is skipped when none of its cars certainly runs: with
  one unattributed outage, a bank of one car is skipped and a bank of two stays.
- Doors with an unconfirmed step-free approach rank after confirmed ones and get a warning.
- The maps are sketches (simplified corridors), so distances are approximate.


## Reading the backend (live closures and buildings)

The engine stays stateless. A request that sends its own `closures` uses them as is (an empty list
means "no closures"). A request that **leaves `closures` out** makes the engine read the backend's
`GET /closures` (cached 5 s). The same goes for buildings: `destination.building` / `origin.building`
can be just `{"id": "ilc"}`, and the engine reads the entrances and elevators from `GET /buildings`
(cached 60 s). An entrance with unknown `step_free` counts as not step-free.

| env | default | |
|---|---|---|
| `BACKEND_URL` | `http://localhost:8000` | empty turns fetching off |
| `BACKEND_TIMEOUT_S` | 3 | |
| `BACKEND_CLOSURES_TTL_S` / `BACKEND_BUILDINGS_TTL_S` | 5 / 60 | |

If the backend can't be reached, the request still runs without closures, and the response says so:
`meta.closures_source` is `unavailable` (others: `request`, `backend`, `none`), `meta.backend_error`
has the reason, and a warning is added to the route. The indoor router does the same.

**Naming an elevator.** A backend closure may carry `asset_id` (and `building_id`). If the id is a car
(`ilc-elevator-core-a`), that car is out. If it is an elevator bank from `indoor_overrides.json`
(`ilc-elevator-west`, the core pair), one car in the bank is out, and which one is unknown unless
only one is still free. Other ids are ignored and the closure is matched by location as before.
`/api/indoor-route` reads closures the same way when `closures` is omitted.


### Map export for the map UI's indoor viewer

| Endpoint | Returns |
|---|---|
| `GET /indoor/status` | `{buildings: [{building_id, name, routable, status: "engine"}]}` |
| `GET /indoor/maps/{building_id}` | The indoor map as this engine routes it (scraper map plus `indoor_overrides.json`: traced floors, doors, elevator cars), in the `contracts/indoor-map.schema.json` shape, `status: "engine"` |
| `GET /api/indoor-plan/{building_id}/{floor_id}.png` | The floor-plan image a traced floor's `image_url` points at (ILC floors 1–2, stitched from the public ArcGIS plans) |

These are the same paths the viewer reads from the `campus_routing` server, so pointing
`VITE_INDOOR_API_URL` at this engine makes the viewer load this engine's maps. `POST /api/indoor-route`
also returns `node_path` and `edge_ids` (one per step between nodes); every id exists in the
`/indoor/maps` document, so a viewer can draw exactly the route the engine chose.
