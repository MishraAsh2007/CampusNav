# Joining indoor drawing directions to outdoor navigation

Implemented in Roles 1 and 3. The existing `POST /journey` now accepts an explicit
`kind: "drawing"` endpoint alongside its existing `indoor` and `outdoor` endpoints.
It composes drawing → entrance → outdoor → entrance → indoor legs, including return
trips. Existing measured indoor requests keep their behavior. The current map UI
also consumes these legs; the combined server reads closures from the shared Data
API. See [the current integration guide](CURRENT_INTEGRATION.md).

## Which joins are enabled

| Building | Status | Evidence or missing connection |
| --- | --- | --- |
| North D | **Enabled:** floor-1 southwest lobby threshold | Official entrance `umass-entrance-50`, inspected first-floor plan and OSM building-outline node `2264382900`, which is also the end of footway `217134889`. |
| Old Chapel | Unavailable for outdoor joins | The cached OSM entrance is beside a historic stair-side entry. The accessible pavilion's exact threshold/path match is unresolved. Its indoor drawing routes still work. |
| Goodell | Unavailable for outdoor joins | Official directions establish west level 3/east level 5, but exact door-to-graph thresholds are unresolved. Official GIS entrance 75 is on the north approach and cannot stand in for either door. Indoor drawing routes still work. |

North D's plan is rotated: its drawing-bottom lobby exit corresponds to the
geographic southwest side. OSM node `2264382900` is shared by the building outline
and the end of a footway, not just a nearby node chosen by distance. Official GIS
entrance 50 is approximately 2.97 m from it and corroborates keycard, push-button
and all-floor access in the August 2022 source edition. The OSM boundary node is
used as the common threshold. No straight walkway is invented between the offset
GIS coordinate and the building.

This is **source matching, not physical verification**. Current access, thresholds,
elevator operation and clearances remain unverified. The request requires drawing
acceptance and residence permission. A resident declaration is not an access credential.

## Collection and validation

`campus_notices/plan_portals.py` checks the pinned plan edition, official entrance
attributes, reviewed OSM coordinate, building-outline membership and footway
endpoint/topology. It generates ignored `data/private/plan_wayfinding_portals.json`.
A revalidation that retracts eligibility removes that join instead of keeping an
older enabled record. Unresolved doors stay in the registry with explicit reasons.
The journey engine also rejects a changed floor hash, moved graph anchor or missing
approach edge when serving a request.

The unified scraper runs the new `plan-portals` stage after `additional-wayfinding`.
Both the registry and drawing maps enter the private combined bundle. The standard
full command remains:

```powershell
.\scrape-all.cmd --rules-only
```

To rebuild just the reviewed maps and entrance matches from downloaded sources:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_additional_wayfinding
.\.venv\Scripts\python.exe -m scripts.build_plan_portals
.\start-indoor-pilots.cmd
```

Use the expanded residence graph configured by this launcher. If an older server
already occupies port 8004, stop it before running the launcher again.

## Try the complete trip

Open **http://127.0.0.1:8004/docs**. `GET /journey/portals` lists source matches and
unresolved doors. In `POST /journey`, use
[`examples/indoor/north-d-to-ilc-request.json`](../examples/indoor/north-d-to-ilc-request.json):

```json
{
  "origin": {
    "kind": "drawing",
    "building_id": "north-d",
    "node_id": "apartment-513-5"
  },
  "destination": {
    "kind": "indoor",
    "building_id": "ilc",
    "node_id": "ilc-source-n111-f1"
  },
  "accept_drawing_only": true,
  "resident_access_confirmed": true,
  "max_grade": 5,
  "no_stairs": true,
  "closures": []
}
```

This starts in the shared hall outside D513, uses the elevator to floor 1, exits
through the southwest lobby threshold, follows outdoor paths, then uses the existing
ILC indoor pilot to reach N111's entryway. Swap `origin` and `destination` for the
return trip. ILC's existing indoor data is also a pilot with its own source limits;
this addition does not physically verify it. Du Bois endpoints from its existing
`GET /indoor/maps/library` map can be used in the same way.

`closures: []` is a graph-only test. In real requests, fetch `/closures`, check
`/closures/status` for freshness/availability, and supply that array. These endpoints
do not trigger scraping. Neither an unavailable feed nor an empty stale cache
establishes that no disruptions exist.

## Response and closure behavior

- `legs` preserves the sequence of indoor, portal and outdoor directions. Consecutive
  elevator floor edges remain one ride, without instructions to exit at intermediate stops.
- A North D portal is a WGS84 **Point** transition at the shared threshold, with its
  entrance ID, sources, keycard flag and evidence. It is not a fabricated LineString.
  Existing measured portals retain their LineString geometry.
- For journeys containing a drawing leg, `total_distance` and `routing_cost` are
  **null**, `distance_complete` and `physical_verification` are false.
  `known_distance_m` sums the known metric legs, excluding unknown drawing lengths.
  Candidate selection minimizes known metric cost; it does not claim the shortest
  total journey when indoor distances are missing.
- An active `closed` closure for North D bank `umass-elevator-148` blocks trips that
  need that bank. An entrance path closure for `umass-entrance-50` blocks the join.
  Expired/future closures and other-building closures do not block it. Same-floor
  indoor trips can still work when the elevator is closed.
- Unknown entrances never fall back to the nearest outdoor path. Complete trips
  without a usable join return `no_journey`. Indoor-only drawing trips remain available.
- Requests requiring measured minimum widths or confirmed automatic doors are rejected
  for these drawing interiors rather than silently relaxing those requirements.

Role 2 can consume this backend contract later. The guided `/navigation/*` resolver
still uses its existing measured-place catalog; this addition does not silently
reinterpret its building/floor choices as drawing endpoints.

## What resolves the remaining doors

For Goodell, obtain a current outdoor coordinate/OSM boundary node and connected
step-free approach for the west level-3 or east level-5 column doorway. For Chapel,
identify the accessible pavilion's actual outer doorway and approach, distinguishing
it from the historic stair doors. Then record the matching plan threshold, entrance
level, access restrictions and source evidence; add a reviewed portal and re-run
the collector/tests. A nearby coordinate alone is insufficient.

Software validation covers both directions, mixed and drawing-only journeys,
permission/consent checks, elevator and entrance closures, expired reports, source
retraction, stale anchors, source hash changes and API integration. The production
North D ↔ ILC request was exercised against the expanded saved graph; the request-local
elevator-outage check correctly returned `no_journey`. No fake report was published.

After this integration, the full Python suite passed **272 tests** and Ruff passed
for `campus_routing`, `campus_notices`, `scripts` and `tests`.
