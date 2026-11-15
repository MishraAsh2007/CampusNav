# Ash_ver integration — 2026-11-15

Compared main `2659763` with Ash_ver `f73e8fc`, then merged the branch history
on `integration/ash-ver-20261115`. The existing `campus_routing.integrated:app`
entrypoint and responsive frontend remain the default application. ILC now opens
with Ash's detailed map; Simple map and Original drawing remain selectable.

## Enabled in the current application

| Addition | Result |
| --- | --- |
| Fourth ILC elevator | North Pleasant Street car beside S110/S220 joins the central pair and N155/N255 car. Four cars are explicitly confirmed by the user. Only floors 1–2 are routed. |
| More ILC destinations | 12 additional hallway approaches: N101, N140 commons/cafe, S110, S112, S122, S131 and floor-1 restrooms; N201, S225, S231, S241 and floor-2 restrooms. Total: 21. |
| Shared map coordinates | Both branches' floor PNGs are byte-for-byte identical. Room polygons marked `method=plan` are folded into the existing simplified map; invented box fallbacks are excluded. No classroom interiors are shown. |
| Three map styles | Detailed map is the ILC default, with Simple map and Original drawing in Map options. Routes and steps stay in the same coordinate frame across all three. The detailed view includes the source-traced N151 upper auditorium on floor 2, which Ash's renderer previously omitted because it had no routing node on that floor. |
| Corrected labels | The printed floor-2 plan labels S241 and S225; Ash's corresponding traces were labeled S211 and S275. The active routes and outlines use the printed labels. |
| Closure identity | Ash's named car IDs map explicitly to the corresponding four pilot assets. Each car can be blocked independently, and closing all four prevents cross-floor routing. Unknown IDs do not snap to a nearby car. |
| Elevator inventory | The source catalog records four ILC cars and five Du Bois cars, with reported evidence. Existing GIS lobby locations, unknown operating status, and indoor bank geometry are kept distinct from car counts. |

The graph now contains **70 landmarks and 72 connections**. Existing destination
IDs and the southwest floor-2 outdoor portal are preserved. Mobile dragging,
pinch zoom, the collapsible directions card, voice toggle, feet/miles display,
loading behavior and the outdoor step-marker fix remain in place.

The source adapter is `scripts/ash_ilc_additions.py`, invoked by
`python -m scripts.build_ilc_plan_routes`. It uses explicit reviewed corridor
joins, checks source image hashes, and retains unknown metric distances and
access measurements. New room approaches are source-based, not field-certified.

## Imported and available separately

The complete Ash branch is retained, including these tools:

| Component | Location | Current use |
| --- | --- | --- |
| Alternative OSMnx/NetworkX outdoor engine | `routing/app/`, `routing/data/graph.graphml` | Separate engine for comparison; not the production default. |
| USGS EPQS/3DEP elevation collection and cache | `routing/app/graph/elevation.py`, `routing/scripts/fetch_3dep.py` | Available for offline graph preparation. Terrain elevations do not measure a sidewalk or raised deck. |
| Ground-truth override framework | `routing/app/graph/overrides.py`, `routing/data/ground_truth.json` | Retained; individual observations still need evidence review. |
| Car-count/bank outage assessment | `routing/app/indoor/elevators.py` | Available in Ash's API. Building-wide/unnamed-car logic has not replaced the current asset-scoped router. |
| Room/floor search and room-to-exit routing | `routing/app/indoor/router.py`, `indoor_api.py` | Retained as a separate API. Current application continues using its explicit node and portal contracts. |
| Generated SVG plans | `routing/app/indoor/schematic.py`, `routing/scripts/plan_outline.py` | Used by `scripts/build_ilc_detailed_maps.py` for the default ILC background; this does not switch to Ash's routing engine. |
| Service Interruption Notice CSV parser | `services/scraper/parse_sin.py` | Optional fallback/import tool. The authenticated SharePoint scraper remains primary. |
| Official-notice publishing helper | `services/scraper/sync_backend.py` | Imported but not run. It performs a read/replace write and can race with another publisher. |

Existing functionality already covered whole-trip entrance selection, indoor
departure/arrival legs, live backend closures, scraper caching and explicit
outdoor-to-indoor handoffs. The merge preserves those flows rather than running
both engines for the same request.

## Why the outdoor engine was not switched automatically

Ash's implementation makes different assumptions that need an explicit decision:

- Short edges under 8 m can exceed the selected maximum slope and still be routed.
  The current engine treats the selected grade as a limit.
- Bridges/tunnels are flattened, and the committed Du Bois ramp override uses
  4.2% from `mockBuildings.ts`; its own evidence says it is not field verified.
- The alternative frontend adapter ignores some preferences, including the
  automatic-door requirement. It cannot directly replace `/plan` without
  preserving current entrance constraints and exact indoor portal metadata.
- Its indoor endpoint can substitute another door when the requested entrance
  cannot route. The current application preserves the actual outdoor arrival.
- Its map exporter supplies nominal widths/grades, and it can route on an
  untraced floor when that floor is the destination. Those assumptions are not
  imported into the current source-plan guide.
- Bank outage semantics still need integration tests before production use;
  for example, the named-asset branch runs before the `scope=all` branch.

The useful next outdoor step is a controlled comparison of known trips using
the USGS elevation cache, keeping strict slope/door constraints and excluding
the sample ramp override. This merge does not claim that comparison is complete.

## Remaining indoor gaps

- Floors above ILC floor 2 are not enabled. Neither a room-number rule nor a
  statement about floor access supplies corridor geometry.
- Other ILC outdoor entrance joins remain unreviewed; the documented southwest
  floor-2 doorway remains the automatic handoff. Ash's entrance observations
  are retained for future matching.
- N151's additional doorway approach needs further tracing before import.
  It remains a displayed room outline, not a new routable destination.
- Du Bois has five reported cars but still one modeled bank in the current app.
  Individual car doors and partial-bank outage behavior are not yet integrated.
- Current physical clearances, thresholds, operation and indoor GPS remain
  unverified/unavailable. The marker represents the selected instruction.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests routing/tests -q --import-mode=importlib
npm.cmd --prefix frontend run test:integration
npm.cmd --prefix frontend run build
```

At integration: **349 Python tests passed** (including Ash's 33 original tests),
**35 frontend tests passed**, and TypeScript/production build passed. Coverage
includes every listed ILC destination in both directions, four independent
elevator alternatives, named-car closures, map alignment, and unchanged entrance
handoff. These are software checks, not physical accessibility verification.
