# Oak House: shared-hall elevator pilot

**Expanded implementation:** see [Oak and central-building wayfinding](EXPANDED_INDOOR_PILOTS.md).
Oak now has all six source floor references, with explicit first-floor connection gaps.
The two-floor example below remains a small subset. Use `start-indoor-pilots.cmd` for the
expanded Oak, Campus Center and Student Union backend catalog.

Oak is the selected Honors College pilot for the clarified scope: navigation starts
in the shared hall outside a room or suite, never inside someone's private space.
This supersedes the Brett-only same-floor pilot as the preferred multi-floor example.

## Why Oak

Birch, Linden, Oak and Maple plans were compared, alongside the earlier Elm inspection.
Oak's first- and second-floor drawings clearly show a central double-shaft elevator bank
and continuous shared circulation near individually numbered room doors. This avoids
having to trace suite interiors. Birch lacks a sourced entrance in the imported catalog;
Linden/Maple have more apartment/suite complexity; Elm's available plans begin at floor 3.

The pilot uses the authenticated official `707-01.pdf` and `707-02.pdf` drawings. Their
hashes are checked before generating the graph. Oak's sourced elevator location is
`umass-elevator-183`; this identifies the bank/location and does not establish car count
or current operation. A drawing match establishes a candidate floor-1/floor-2 connection,
not an independent inspection of operating service.

## Implemented route

**Shared hall outside Room 233 → second-floor central elevator landing → elevator to
floor 1 → lobby 125 → exterior doorway.** The reverse sequence also works.

There are nine floor-specific waypoints and eight connections. No segment enters Room
233 or a private suite. Elevator geometry uses separate landing points on each drawing;
the response never draws a corridor line between different floor images.

This is drawing-based wayfinding. Distances and maximum grade are returned as `null`
rather than invented. Current elevator operation, access permissions, door clearances
and final geographic entrance alignment are not verified. The endpoint is the floor-plan
doorway; it is not silently snapped to an OSM point or joined to an outdoor journey.
Only floors 1 and 2 and the traced shared-space segment are supported, not all of Oak.

## Try it

```powershell
.\start-oak-pilot.cmd
```

Open <http://127.0.0.1:8004/docs> and expand **Drawing wayfinding pilot**.
Use `POST /plan-wayfinding/oak`, click **Try it out**, and enter:

```json
{
  "start_node_id": "outside-233",
  "end_node_id": "exit-threshold",
  "accept_drawing_only": true,
  "resident_access_confirmed": true,
  "closures": []
}
```

The booleans explicitly acknowledge the drawing-only scope and permission to use the
residence interior. They are planning declarations, not authentication credentials.
The empty closure list is an isolated test; real callers must pass the current merged
closure feed. The endpoint does not fetch live closures automatically.

`GET /plan-wayfinding/oak` provides the available waypoint IDs and floor-specific source
evidence. This pilot is opt-in through `PLAN_WAYFINDING_DIR`; default servers do not
expose private drawing graphs. Original PDFs and images remain in the ignored private
directory. No frontend implementation or map auto-reroute hookup was added here.

Command-line route and outage checks:

```powershell
.\.venv\Scripts\python.exe -m scripts.trace_oak_wayfinding --route --accept-drawing-only --resident-access-confirmed
.\.venv\Scripts\python.exe -m scripts.trace_oak_wayfinding --route --accept-drawing-only --resident-access-confirmed --close-elevator
```

The outage command intentionally returns `no_plan_path` and a nonzero exit code.
The source map models this bank only, so it does not invent a second usable elevator
or use stairs when the bank is unavailable. Reports scoped to floor 1 or 2 block the
ride; an unrelated floor-3 report does not. Same-floor lobby travel remains available.

## Inspect the floor traces

Generated private artifacts:

- `data/private/plan_wayfinding/oak.json`: multi-floor topological graph.
- `data/private/plan_wayfinding/oak-floor-1.svg`: first-floor trace over the source plan.
- `data/private/plan_wayfinding/oak-floor-2.svg`: second-floor trace over the source plan.
- `data/private/plan_wayfinding/oak-last-route.json`: most recent successful CLI route.

The SVGs were rendered and visually inspected. Generator output recreates these files.
The geometry and source references stay private; they are not automatically pushed to GitHub.

The full Python suite passes **220 tests**. Dedicated tests cover cross-floor and reverse
travel, no private-room entry, exact elevator asset matching, floor-scoped closures,
same-floor travel during an outage, missing served-floor evidence, and opt-in API behavior.

## Next checks for an outdoor-to-room journey

Confirm the actual elevator floor labels and current operation; match the traced floor-1
door to the OSM entrance; verify the outside approach and resident-access requirements.
Those checks are limited to this shared-space pilot. There is no need to map bedrooms,
kitchens or private suite passages to finish this route's scope.
