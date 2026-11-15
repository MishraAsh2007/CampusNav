# ILC navigation on the original floor plans

The new pilot traces selected hallway routes in the original UMass ArcGIS
floor-1 and floor-2 mosaics. The frontend draws route segments directly in that
image coordinate frame. It does not use the withdrawn star-shaped graph.

The default **Simple map** is now a vector tracing of the major classroom
outlines, foyer/circulation areas and elevator shafts. Classroom interiors and
furnishings are omitted. These are approximate traced shapes, not measured room
dimensions or new routable destinations. **Original plan** restores the source
image. **Focus this step** enlarges the current instruction area for phone use.
The route uses the same coordinates in both views.
Elevator icons mark the centers of the crossed shaft boxes on the source plans,
as confirmed by the user. Routing endpoints remain on the hallway side of the
elevator doors; they are deliberately distinct from the shaft-center icons.

## Included coverage

- Southwest entrance starts on floor 2; north entrance beside N155 starts on floor 1.
- North elevator beside N155/N255, two separate central elevators opposite S140/S142,
  and the North Pleasant Street elevator beside S110/S220. The user confirms four cars.
- Floor 1 destinations: N155, N111, S142, S140 hallway approach, S120 hallway approach.
- Floor 2 destinations: N255, N211, S240 hallway approach, S220 hallway approach.
- Ash_ver additions: N101, N140 commons/cafe, S110, S112, S122, S131 and restrooms
  on floor 1; N201, S225, S231, S241 and restrooms on floor 2. These add 12 approaches
  for 21 total. S225/S241 correct the branch's S275/S211 labels using the printed plan.
- Floor-specific route lines, floor selector, zoom/pan, selected-step marker, and Back/Next.
- Each elevator can be blocked independently by a scoped closure; all four blocked
  produces no cross-floor route. Named Ash_ver car IDs are explicit aliases of the
  matching pilot assets. Unknown asset IDs cannot be matched by proximity.

These are selected approaches, **not complete room coverage**. Floors 3–4 are not
included. Door operation, grades and widths remain unverified; the API therefore
uses drawing consent and returns unknown metric distance and grade. The floor
plans and reported elevator identities do not establish current physical access.

## Open it

For the normal handoff, open `/`, plan an outdoor route to ILC, and choose
**Go inside** at arrival. A matched entrance supplies the indoor start automatically.
The `?indoor=ilc` shortcut skips the outdoor route entirely; its location picker
is intentional because there is no preceding arrival to inherit.

For a direct indoor-only test, open the frontend with
`/?indoor=ilc`, choose your actual starting landmark (for example **Southwest
entrance - floor 2**), then select a destination. Floor-plan directions are enabled
automatically; the UI sends `accept_drawing_only: true` for indoor and journey requests.
The simplified map stays visible alongside a compact directions card: on the
right on laptops, and below the map on phones. Phones focus the current step;
the focus button toggles the full floor. Next/Back advance the selected
instruction and automatically switch floors after the elevator step. The blue
marker is not live GPS. **All steps** opens the complete itinerary; the layers
button contains the original-plan toggle and source details. There is no
separate next-instruction ("Then") preview.

Spoken indoor steps are on by default. Next, Back and selecting a step read the
new instruction. Use the speaker toggle to turn voice off/on; turning it on
reads the current step. The repeat button reads the current step again. Exiting
indoor navigation stops speech. Voice controls are disabled when the browser
does not support speech synthesis.

The southwest threshold now connects to outdoor OSM entrance `6382267406`,
which explicitly records level 2. The floor-plan doorway aligns within one meter
of that node. `/plan` accepts `prefer_indoor_entrance: true` and prefers this
entrance if the route satisfies the user's constraints. Its `indoor_arrival`
identifies `ilc-entrance-south` on floor 2, so Go inside starts there automatically.
`/journey` also supports an outdoor-to-ILC-room route through that same threshold.

The historical GIS point 56 is several meters outside and is **not** an alias.
The north entrance has no established outdoor join. Arrivals at unmatched doors
explain why continuation is unavailable; users can explicitly choose to start a
separate indoor route at a known landmark. The final southwest outdoor edge has
an estimated 6.5% grade. The frontend default is now 7% at the user's request;
lower selected limits still block that approach. A peer-confirmed push-button
opener is now linked to the southwest floor-2 doorway. Operating-test results,
door clearances and interior access remain unknown.
This is source matching, not a physical access survey or indoor GPS tracking.

The UI labels an unmatched arrival as **Indoor connection unavailable — view
details** and displays the matched entrance's routing failure (including
automatic-door requirements). It does not imply a continuous trip when the outdoor
route stops at a different point. The withdrawn ILC Main Corridor topology is
explicitly blocked by the frontend even if an older API calls it reviewed. HTML
and indoor metadata use `Cache-Control: no-store` to avoid retaining old editions.

## Files and source provenance

- `data/plan_wayfinding/ilc.json`: 70 landmarks, 72 connections, 4 elevator assets.
- `data/plan_wayfinding/sources/ilc/`: exact PNG mosaics and source tile extents.
- `data/plan_wayfinding/sources/ilc/display-trace.json`: display-only outlines,
  bound to each source image's SHA-256. A different source edition disables
  this overlay until retraced. The routing graph never consumes these shapes.
- `scripts/build_ilc_plan_routes.py`: explicit pixel traces, labels and source-edition checks.
- `scripts/ash_ilc_additions.py`: reviewed corridor joins and room outlines from
  Ash_ver. Both branches' PNG sources have identical hashes; box fallback shapes
  are excluded. See [the merge comparison](ASH_VER_MERGE.md).
- `scripts/build_ilc_portal.py`: validates the southwest OSM entrance, floor, approach
  and source-image alignment; updates `data/plan_wayfinding_portals.json`.
- `campus_notices/plan_integrity.py`: approved source image fingerprints; changed
  source imagery cannot silently reuse this trace.
- `frontend/src/components/indoor/SourceRoutePlan.jsx`: per-floor SVG overlay on the source image.

The backend uses `data/plan_wayfinding` by default; an existing
`PLAN_WAYFINDING_DIR` environment variable overrides it. Images are served by
`/plan-wayfinding/ilc/floors/{1|2}/image`, so there is no runtime ArcGIS dependency.
Rebuild the trace with `python -m scripts.build_ilc_plan_routes`. The script uses
the downloaded audit edition if present, or the checked-in source edition.
Revalidate the outdoor handoff with `python -m scripts.build_ilc_portal` after
rebuilding the trace. Its public OSM source is saved beside the plan mosaics as
`southwest-approach.osm`; no login is needed.

The original public sources are:

- https://www.arcgis.com/home/item.html?id=b3d4d6b388c149bf8b9e76bc9d460c45
- https://www.arcgis.com/home/item.html?id=131a52d2430b45c3b27f9e7294a3800f

The map was inspected as a route overlay against both source plans. Regression
checks exercise every listed destination in both directions, elevator alternatives,
closed-elevator rejection, consent, image fingerprints and separation of floors.
Physical walk-through and phone-browser visual verification remain outstanding.
