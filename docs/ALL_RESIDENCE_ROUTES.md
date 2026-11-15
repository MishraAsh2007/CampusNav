# All-residence route implementation and verification

This extension covers the 51 distinct residence buildings in the downloaded plan inventory.
It is a separate configuration so the existing central-campus demo remains reproducible.

The completed Campus Center round-trip audit found a walking comparison for all 51
destinations, a no-stairs route for 8 at a 5% grade limit, and a no-stairs route for 36
at an 8.33% limit. These are separate profiles. See the
[dorm-by-dorm results](RESIDENCE_ROUTE_COVERAGE.md); failures remain explicit.
The implementation passed 207 Python tests and Ruff, with HTTP checks of the expanded
map, building list, health, API docs and representative route requests.

## Run the expanded outdoor map

```powershell
.\start-residences.cmd
```

Stop an existing port-8000 server first. This launcher selects
`data/umass-residences.graph.json` and `data/residence_buildings.json` through the
`ROUTING_GRAPH` and `BUILDINGS_PATH` environment variables. It uses the existing map UI
and `/plan` routing API; no new frontend code is required to list the larger catalog.
The existing guided indoor conversation still requires an imported indoor map.

The expanded graph has **10,822 nodes and 24,306 directed edges**, including 450 stair
edges and 8 ramp edges. All edges have terrain-derived or source incline grade values.
Terrain estimates are not surveyed grades or an accessibility compliance assessment.

## What each destination means

- 51 residence buildings matched official UMass footprint records.
- 34 sourced entrance points are available across 23 residences, combining the public
  accessibility layer and OSM entrance records.
- 28 residences still have no sourced entrance. Their destination is a clearly labeled
  **outdoor meeting point** on the main walking-network component outside the official
  footprint, within 100 meters. The measured gap to the footprint is stored separately.
- Meeting points do not establish a usable door, a step-free final approach, resident
  permission, or an indoor connection. Those fields remain unknown.

The source accessibility map is labeled August 2022. Newly collecting its records does not
verify current door or elevator operation. Some entrances require a keycard; the normal
public-entrance filter still excludes them. API callers can explicitly set
`allow_keycard_entrance_approach: true` to plan an **outside-only** approach, with a warning
that permission to enter has not been established. No access flags are rewritten.

## Repeat the source and route checks

```powershell
.\.venv\Scripts\python.exe -m scripts.fetch_residence_access
.\.venv\Scripts\python.exe -m scripts.fetch_residence_osm
.\.venv\Scripts\python.exe -m scripts.build_residence_catalog
.\.venv\Scripts\python.exe -m scripts.audit_residence_routes
```

These source downloads happen outside route requests. The source layers are cached below
`.cache/`; generated catalogs and the graph are independent of login sessions. The catalog
join uses the local private plan inventory for building identity and retains source aliases.

`data/residence_route_audit.json` records each dorm's outbound and return result from Campus
Center under two separate step-free grade limits: 5% and 8.33%. Each check uses an explicit
empty closure list to isolate graph coverage. The higher limit is a separate test, never
a silent fallback. Real requests must include current closures. A route computed from this
origin is not proof that every pair of dorms is reachable.

Each result records a selected entrance ID, network snapping gap, and whether an unconstrained
comparison route exists. Missing or infeasible paths remain `no_route`; the audit does not
create fake geometry to make the count reach 51. Outdoor meeting points are distinguished
from sourced doors in the audit.

## Indoor status

There are **no completed real residence indoor maps yet**. Brown's candidate corridor
annotation and all 51 private workspaces remain preparation assets. Actual suite doors,
public/resident-only corridors, documented distances, elevator served-floor lists and
outside-to-entrance connections must be traced and reviewed per building before import.

The shared backend supports additional imported residence maps, exact asset/floor closures,
stairs/grade constraints, arrival confirmation and elevator detours. That capability does not
turn a floor-plan image or a label position into a reliable indoor graph. In particular,
the all-residence outdoor meeting points must never be reused as indoor portals.

See [residence mapping work](RESIDENCE_NAVIGATION.md) and
[missing evidence](INDOOR_DATA_NEEDED.md) for the remaining work.
