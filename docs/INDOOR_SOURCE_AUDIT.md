# ILC and library: public indoor-source investigation

Checked November 14, 2026. These findings describe the public sources actually inspected;
they do not establish that UMass has no additional internal drawings. Source observation
times are stored separately from a drawing's publication/revision date.

## The interactive accessibility map

Yes, the [map supplied in the conversation](https://www.arcgis.com/apps/instant/basic/index.html?appid=4575634567794afd863c83bc4d6d6d4a)
is usable as a data source. Its [app configuration](https://www.arcgis.com/sharing/rest/content/items/4575634567794afd863c83bc4d6d6d4a/data?f=pjson)
points to [web map f24d025261544c678aa5cd372ddae62b](https://www.arcgis.com/sharing/rest/content/items/f24d025261544c678aa5cd372ddae62b/data?f=pjson).
The inspected map exposes five operational layers:

| Layer | Useful information | Indoor-routing limit |
| --- | --- | --- |
| AccessibleParkingSpaces | Parking positions | Does not connect a parking space to a building interior |
| Entrances | Mapped entrance coordinates and access attributes | Does not give a complete interior corridor or entrance-floor graph |
| Elevators | Elevator locations | Does not enumerate documented landings and served-floor connections |
| Restrooms | Room label, building, explicit floor, position and access attributes | A room point is not a doorway or a walkable connection |
| BuildingData | Building names, footprints and accessibility attributes | A building polygon is not a floor plan |

The app labels its accessibility data August 2022. Re-fetching it today does not establish
current door access or elevator operation. The separate interruption scraper supplies
outage reports; it cannot supply the missing corridor geometry.

## Sources now collected automatically

| Source | Successful snapshot | What is retained |
| --- | --- | --- |
| [Du Bois directory](https://www.library.umass.edu/du-bois-library/) | 27 records | Service names and explicitly stated floors/features |
| [Library floor maps](https://umass.stackmap.com/explore/) | 26 Du Bois images | Actual image URLs and floor labels; revision/scale must be checked |
| [Campus Center directory](https://www.umass.edu/af/space-use/campus-center) | 24 records | Rooms and explicitly named floors; outside the new two-building guided pilot |
| [ILC classroom directory](https://www.umass.edu/registrar/room-types-and-capacities-ilc) | 16 rooms | Room IDs, capacity, type, details; N151 explicitly has first- and second-floor entryways |
| [Restrooms feature layer](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Restrooms/FeatureServer/0) | 57 pilot records: 38 library, 19 ILC | Source `FLOOR`, room, coordinates, ADA/description/transfer fields; staff-only descriptions preserved |
| [Student study spaces view](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Campus_Buildings_StudentStudySpaces_View/FeatureServer/0) | 5 ILC records | Explicit `Floor`, `RoomNumber`, geographic position and original attributes |

Total: **155 references**, including **91 library**, **40 ILC**, and **24 Campus Center**.
These are source records, not counts of unique navigable destinations: sources can overlap.
Use `.\refresh-indoor.cmd` and inspect `data/indoor_sources.json` or `GET /indoor/sources`.

A separate [library elevator collector](LIBRARY_ELEVATOR_COVERAGE.md) now reads
the actual StackMap floor-detail pages: 26 floors, 52 grouped elevator regions,
and a dated directory identifying five cars. These records are stored separately
in `data/library_elevator_sources.json`; they are not additional production routing
assets. The owner reports all five cars now serve all floors; the directory's
2007 express/local restrictions are not applied. See also the
[central-building source gaps and SharePoint results](INDOOR_COVERAGE_GAPS.md).

One important discrepancy: the study-space layer records **N201 with `Floor: "01"`**.
We preserve that field; we do not infer floor 2 from the room number. Numeric `01` can be
normalized to `1`, but `E`, `LL`, `BT` and `Lower Level` are not assumed equivalent without
review. Access flags are preserved as source evidence, not promoted into a routable graph.

## Other leads checked

| Lead | Observed result | Decision |
| --- | --- | --- |
| [ILC building page](https://www.umass.edu/planning-design-construction/book/integrative-learning-center-2014) | Building context and imagery; no usable indoor graph obtained | Keep as context |
| [ILC room-features page](https://www.umass.edu/registrar/room-features-ilc) | Classroom-type information and prototype illustrations | Do not treat prototype layouts as the actual ILC floor plan |
| [Indexed 2018 ILC building manual](https://www.umass.edu/cp/sites/default/files/Integrative%20Learning%20Center%20%28ILC%29_Building%20User%20Manual_2018_02_28_Compressed.pdf) | Search index mentions floor/egress plans; opening the actual URL redirects to the PDC homepage | No PDF downloaded or geometry imported |
| Same manual filename under the migrated PDC file directories | Root, `2024-10/` and `2024-11/` paths returned HTTP 404 | No substitute drawing assumed |
| Additional `Elevators_PNTS` and `Entrances_PNTS` ArcGIS layers | Pilot features did not supply populated floor-stop connections or linked plan images | No extra indoor edges inferred |
| ArcGIS service named `Corridors` | Feature extent was outside UMass, in Australia | Excluded despite its promising name |
| ArcGIS service named `Floors_to_Review` | Description identified Pompeii | Excluded as unrelated |
| [Campus Atlas, HackUMass IX](https://fuseumass.github.io/HackUMass-IX-Projects/21.html) | Prior student indoor-map project; linked GitHub repository returned 404 through the available connector | No code or campus geometry imported |

The service-name checks used the public
[UMass organization service catalog](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services?f=pjson).
An organization can host unrelated student datasets, so the service name alone is not evidence
that its geometry describes this campus.

## What remains before real directions

For each pilot, we need documented public corridors, room doorways, actual elevator landings
and floors served, entrance levels, measured/sourced distances, and the connection to the
outdoor graph. The library images are a useful tracing source, but symbols alone do not
confirm elevator service, scale, access or current obstacles.

UMass provides a [service/space and drawing-request process](https://www.umass.edu/facilities/service-space-requests)
for obtaining building plans. No request has been sent. If a usable plan becomes available,
the existing [map schema and import workflow](INDOOR_MAPPING.md) can accept the traced data
without changing the navigation API. The [guided API](GUIDED_NAVIGATION.md) already handles
the complete staged trip using reviewed connections.
