# ILC field corrections — 15 November 2026

**Current implementation:** a separate floor-plan pilot now serves floors 1–2
through `/plan-wayfinding/ilc`. See [ILC_PLAN_NAVIGATION.md](ILC_PLAN_NAVIGATION.md).
The withdrawal described below still applies to the old measured indoor graph,
not to the new opt-in, drawing-based pilot.

ILC indoor navigation is suspended pending a new topology review. The previous
`reviewed` status was unjustified: floor-plan references and graph connectivity
did not establish that the depicted corridor paths and entrance matches were correct.
The previous automated tests checked connectivity, not agreement with the building.

## Observations relayed by the user

These are peer observations, not a facilities survey. Preserve that distinction.

**Latest entrance update:** the user confirmed a push-button opener at the
southwest floor-2 doorway. Its exact OSM threshold now carries that peer evidence
in the building catalog and drawing portal. See
[ILC_ENTRANCE_AUDIT.md](ILC_ENTRANCE_AUDIT.md). This does not reinstate the old graph
or verify door widths and path grades. The frontend's adjustable default slope
limit is 7%; the existing 6.5% estimated approach grade is unchanged.

| Observation | Data action | Still needed |
| --- | --- | --- |
| The entrance we called South is the southwest entrance and enters floor 2 | Correct its label and floor; remove its old floor-1 corridor and outdoor handoff | Match the actual doorway to its GIS record and floor-2 plan position, then document the route from that doorway |
| The friend could not find the entrance we called West | Remove it from indoor entrance nodes and handoffs | Identify the actual doorway, if any; do not infer one from the compass label |
| An unnamed elevator in the north serves floors 1 and 2 | Record the observation without inventing coordinates or a third elevator | Match it to an existing shaft, or establish a distinct shaft; identify its floor-1 and floor-2 landing positions and corridor approaches |
| Location was not tracked | State that indoor progression is manual | Reliable indoor positioning requires infrastructure or landmark confirmation; outdoor phone GPS alone cannot resolve indoor floors/corridors |

The corrected southwest record retains its stable ID `ilc-entrance-south` for
compatibility. Its historical GIS position and old x/y are retained only as
unreviewed candidate data. They are **not** a confirmed doorway location on floor 2.
Removed nodes, incident edges, and portal records are archived in
`data/reviews/ilc-field-review.json`. The remaining ILC edges are draft candidate
data, including the old East/West elevator labels and unconfirmed higher-floor stops.
No ILC indoor route is served until the map is reviewed again.

## Minimum work to restore useful navigation

Start with one real trip, not every floor: the southwest floor-2 doorway to one
identified room, and the north elevator connection between floors 1 and 2.
Record each threshold/landing against the correct published plan, the actual
hallway turns, signs or room numbers at decisions, and any door or level change.
An annotated screenshot plus a walk-through in both directions is sufficient to
begin review; a room directory or a building-wide accessibility symbol is not.
The north elevator does not need an official name: use a stable asset ID and
a user-facing description based on a nearby permanent landmark once identified.

Compare the resulting route with the physical walk before setting `status` back
to `reviewed`. Recheck entrance identity, floor transitions, both travel
directions, and elevator-outage behavior. Update the scraper's curated review
inputs; a refresh must not promote a candidate connection automatically.

## Display and location

The new guide presents the route as ordered instructions and landmarks. It no
longer turns the graph into an apparent floor plan. Original plan images can be
shown separately; a route overlay requires a reviewed alignment and traced
corridors. A truthful path visualization can also be a clearly labeled,
non-spatial sequence of steps, without implying position or corridor geometry.

Correction after inspecting Role 2's code: browser location tracking **was**
implemented in `indoorGps.js`, using `navigator.geolocation.watchPosition`.
`IndoorFlow.jsx` projects the fix onto a floor and snaps it to the route;
`altitudeFloor.js` estimates floors from altitude. The integration disables this
for API-sourced maps (`gpsOn && !reviewed`). In that mode the former marker
followed the selected step. Sample calibration stretches the building's OSM
bounding box over the sample plan; that is not evidence of corridor alignment.
Altitude estimation assumes floor spacing and can default to floor 1, so it
must not silently determine an entrance level. Manual Next/Back and confirmation
of a known starting landmark are the currently supported source-map workflow. A future
QR landmark can provide an exact confirmed start; continuous movement tracking
would require additional positioning capabilities.

## Public imagery retrieved on 15 November 2026

Both registered ArcGIS services currently return public PNG tiles, even though
their HTTP content type is `application/octet-stream`. Check the image bytes;
do not reject a valid PNG solely for that content type. No login was required.

- Floor 1 item: https://www.arcgis.com/home/item.html?id=b3d4d6b388c149bf8b9e76bc9d460c45
- Floor 2 item: https://www.arcgis.com/home/item.html?id=131a52d2430b45c3b27f9e7294a3800f
- Local original mosaics and georeferencing metadata: `data/private/ilc-plan-audit/`.
  Each floor uses the original level-20 tiles, 1536 × 1280 pixels. Metadata
  records the **tile mosaic** extent, not merely the service's fullExtent.
- Higher resolution north-wing details: `north-floor-1.png` and
  `north-floor-2.png` in that directory.

Visual inspection shows matching lift-shaft symbols immediately beside N155
and N255. The user has now confirmed this is the unnamed north elevator and
separately reported two elevators opposite S140/S142. Higher-resolution public
tiles confirm two adjacent shaft symbols across the hall from S142/S140, with
a corresponding pair on floor 2 above S240. The plan labels appear to be
S199Q/S199P and S299Q/S299P respectively; these are plan identifiers, not official
elevator names. There are therefore three identified shaft positions across
these two floors. Higher-floor service and association with old GIS asset IDs
remain unconfirmed. See `central-floor-1.png` and `central-floor-2.png` in the
audit image directory. The previous graph's
East/West shafts clustered at the central corridor and omitted this location.
The real plan also has bent and branching corridors unlike the old schematic.
Retrieve/trace actual door thresholds and corridor centerlines from these
images before restoring routes. Existing graph coordinates must not be overlaid
as if they were already aligned or considered reviewed just because image
dimensions happen to match.

The indexed 2018 building manual still redirects to the PDC homepage. The
official ILC project page links a Green Building Brochure on SharePoint, but
that brochure has not been retrieved or used to establish corridor geometry.
