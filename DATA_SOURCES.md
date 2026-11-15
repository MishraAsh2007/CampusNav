# CampusNav data sources and expected outputs

For the complete application flow and the indoor implementation roadmap, read
[the application guide](docs/APPLICATION_GUIDE.md).

Updated November 14, 2026. This describes the implemented local integration, including its
gaps. Refresh times indicate when our code read a source, not when somebody inspected a door.

## What each source contributes

Use **`.\scrape-all.cmd --rules-only`** to collect these families in one workflow.
The [unified scraper guide](docs/UNIFIED_SCRAPER.md) explains the combined public/private
outputs, per-source freshness and unchanged-PDF reuse. This replaces running several
workers manually; their individual commands remain available.

Additional source investigation resolved the Campus Center concourse-to-bank gap
using a 2026 annotated conference plan and current Hotel UMass directions. See
[remaining indoor coverage and evidence](docs/INDOOR_COVERAGE_GAPS.md) for those links,
the alternate Oak drawing comparison and the Student Union search results. These
documents are collected as references; only explicitly authored, reviewed connections
enter the indoor wayfinding graph.

**Indoor mapping update:** [Role 1/Role 3 indoor handoff](docs/INDOOR_MAPPING.md) documents the
new floor-aware router, combined journeys and topology-review workflow. Run
`.\refresh-indoor.cmd` to refresh the public sources below. The latest fetch produced 155
records and draft floor references; those drafts are displayable but not routable yet.
The [source investigation](docs/INDOOR_SOURCE_AUDIT.md) records the interactive map's layers
and unsuccessful floor-plan leads. The [guided API](docs/GUIDED_NAVIGATION.md) covers the
new library–ILC conversation and routing flow.

| Indoor source | Expected output | Current use |
| --- | --- | --- |
| [Du Bois floor directory](https://www.library.umass.edu/du-bois-library/) | Explicit floor/service/features associations | 27 directory entries; no inferred corridor geometry |
| [Library floor-map index](https://umass.stackmap.com/explore/) | Floor label and public image URL | 26 Du Bois plan references; floor aliases, scale and connectivity still need review |
| [Campus Center room directory](https://www.umass.edu/af/space-use/campus-center) | Room paired with explicitly named floor | 24 room/floor records; no guessed room coordinates |
| [ILC classroom directory](https://www.umass.edu/registrar/room-types-and-capacities-ilc) | Room ID, capacity, type and explicit entry floors where stated | 16 rooms; no floor inferred from room number |
| [UMass Restrooms layer](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Restrooms/FeatureServer/0) | Room, building, explicit floor, position and original access attributes | 57 library/ILC records; points are not doorways or corridors |
| [UMass study-spaces layer](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Campus_Buildings_StudentStudySpaces_View/FeatureServer/0) | Explicit floor, room label and geographic point | 5 ILC records; source N201 has floor `01`, preserved for review |

The scraper stores these in `data/indoor_sources.json`; its first run creates draft
`data/indoor/library.json`, `data/indoor/ilc.json` and `data/indoor/campus-center.json`.
Existing drafts/reviewed maps
are never overwritten by a source refresh. Indoor node/edge/portal geometry is published
separately after review, and located asset IDs can be exported into the notice registry.

| Source | What we expect to extract | What we use it for | Current connection and limits |
| --- | --- | --- | --- |
| [UMass interactive accessibility map](https://www.arcgis.com/apps/instant/basic/index.html?appid=4575634567794afd863c83bc4d6d6d4a) | Building footprints and names, access classification, entrance coordinates, automatic-opener and keycard flags, all-floor accessibility flag, elevator point locations | Building cards, public entrance choices, and coordinates for matching maintenance notices | Public ArcGIS feature layers imported successfully. The app labels the data **August 2022**. Not evidence that a door/elevator works today. |
| [OpenStreetMap](https://www.openstreetmap.org/#map=17/42.3906/-72.5287), through [Overpass](https://overpass-api.de/api) | Walking ways, nodes, geometry, steps/path tags, access restrictions, any available wheelchair and entrance tags | The routing graph and supplemental entrance positions | Real graph built using OSMnx: 6,885 nodes / 15,618 directed edges. Tags and interior connections are incomplete. Missing tags remain unknown. |
| [Open Topo Data NED 10m](https://www.opentopodata.org/datasets/ned/) ([API endpoint](https://api.opentopodata.org/v1/ned10m)) | Terrain elevation in meters at graph-node coordinates | Estimate absolute edge grade as elevation difference / path length × 100 | Elevation batches cached; graph has terrain-derived grades. These are not surveyed sidewalk/ramp slopes, and do not establish ADA compliance. |
| [UMass Facilities service interruption notices](https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx) | Notice ID, building, category, description, effective start/end date and time, source reference | Official closed/degraded closures after rules or optional Gemini parsing and a unique mapped asset match | Live authenticated scraper works with the operator's saved session. Raw notices stay private. Students use the backend without a UMass login. |
| [PVTA service alerts](https://www.pvta.com/bus_service/service_alerts___detours.php), [alert embed](https://pvta.us/swiftly/RevizeAlerts2.php) | Alert title/body, affected route badges, source URL, publication time when available | Discover nearby detours or disruptions for review | Fetched live. Filters configured UMass routes. A bus detour alone does **not** close a pedestrian edge. |
| [Massachusetts Daily Collegian RSS](https://dailycollegian.com/feed/) | Article title, snippet, URL, publication time | Discover recent accessibility/construction/transit reports for review | Fetched live. A successful fetch can yield zero relevant recent items. Articles can be old or imprecise. |
| [r/umass](https://www.reddit.com/r/umass/) | Recent posts and, via the authorized API, comments; text, permalink, and publication time | Potential community complaints for review | Uses the public feed when no API token is configured. Uses the authorized API when credentials are configured. |
| Facebook Page Graph API | Configured Page posts, text, permalink, publication time | Potential community complaints for review | Adapter implemented, **not configured**. No Page selected or authorized token. Arbitrary groups/private profiles are not scraped. |
| CampusNav's Report button | User-selected location or mapped elevator, issue type, broken/working state, timestamp, optional description | Community closures and confirmations | Implemented with a local file for integration testing. Active reports expire after 24 hours; confirmation extends expiry. MongoDB Atlas storage is still Role 4's handoff. |
| Downloaded UMass spreadsheet | Exported notice fields, when live and saved scrape are both unavailable | Last-resort fallback for the official notice pipeline | Not the primary source. Default `~/Downloads/Book1.xlsx`; override with `--fallback-spreadsheet PATH`. Explicitly labeled as fallback. |

The map background uses [OpenStreetMap tiles](https://tile.openstreetmap.org/) by default.
Tiles are visual context, not another routing database. A configured Google Maps key can
change the background renderer; it does not replace the Python routing engine.

## Exact UMass map layers

The interactive app uses web map `f24d025261544c678aa5cd372ddae62b`. We read public JSON
features instead of trying to extract coordinates from map screenshots.

| Layer | Fields requested | Interpretation |
| --- | --- | --- |
| [BuildingData/0](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/BuildingData/FeatureServer/0) | `OBJECTID`, `BuildingID`, `BuildingName`, `AccessLevel`, polygon geometry | Join entrance/elevator points to nearby building footprints. A building centroid is for display; it is not substituted for a missing entrance. |
| [Entrances/0](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances/FeatureServer/0) | `OBJECTID`, `IsKeyCardRequired`, `hasAutoDoorOpener`, `isAccessibleToAllFloors`, point geometry | Preserve powered-door and restricted-access information. An all-floors-accessible entrance is recorded as step-free per the source; other entrances retain unknown step-free status. |
| [Elevators/0](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Elevators/FeatureServer/0) | `OBJECTID`, `Description`, point geometry | Mapped elevator location only. One point may represent a bank. It does not provide car count, floors served, current operating status, or walkable interior connections. |

The current selected catalog contains **7 buildings, 12 entrance positions and 8 elevator
locations**. Campus Center, ILC, Student Union, Du Bois Library and Goodell are in the current
routing area. Patterson and Grayson are included to locate their official notices, but are
outside the current walking graph and aren't offered as routing destinations.

Coverage: longitude −72.536 to −72.519, latitude 42.3835 to 42.3955. Being inside the box does
not guarantee a connected route under a given slope limit. OSM supplementation gives some
buildings an entrance position without proving that its approach or door is step-free.

## How we combine the evidence

1. **OSM provides paths; UMass provides building/asset positions.** Nearby entrance points
   are combined conservatively. Each entrance keeps its source URL. Ambiguous joins between
   adjacent buildings are excluded. Nearby contradictory wheelchair restrictions exclude a
   candidate door from step-free selection pending review.
2. **A notice describes an issue; the registry supplies its coordinates.** Clear phrases go
   through the deterministic rules parser. Ambiguous text can use Gemini on the ingestion
   worker. Neither parser may invent coordinates. An unresolved asset or time goes to review.
3. **Time controls activity.** Scheduled notices appear under upcoming notices. Only issues
   whose start time has arrived and whose end time has not passed enter `/closures`.
4. **Issue type controls graph matching.** A path closure affects intersecting graph edges
   within its meter radius; elevator/ramp closures match the corresponding edge type. A
   closed edge is removed; a degraded edge costs five times its distance. Unmatched closures
   produce a warning. The current real graph has **no indoor elevator edges**, so an elevator
   notice can appear on the map without producing a detour.
5. **Public complaints remain review items.** PVTA, news, Reddit and Facebook candidates
   never automatically become route closures. The app shows them separately. There is no
   approval/promotion UI yet. Repeated scraping does not reset a post's age.
6. **Direct student reports are a separate stream.** A broken/blocked report creates a
   24-hour community closure. A working report clears matching community reports, not an
   official closure. The proposed 12-hour conflict-priority policy and Atlas TTL indexes are
   not implemented by this local store.
7. **Missing evidence stays visible.** Unknown door access, missing interior topology,
   stale source data, and unconnected graph sections are not filled with invented values.
   The 5% setting is a user routing preference, not an accessibility certification.

## Files, commands and API outputs

Run from the project root in PowerShell:

| Operation | Command | Output / consumer |
| --- | --- | --- |
| Build walking graph and elevation cache | `.\build-campus.cmd` | `data/umass.graph.json`, `.cache/osm/`, `.cache/`; `/route` and `/plan` |
| Import official map + cached OSM entrances | `.\.venv\Scripts\python.exe -m scripts.sync_campus_access` | `data/buildings.json`, `data/location_registry.json`; `/buildings` and `/buildings/status` |
| Save authorized UMass session | `.\login-notices.cmd` | Private `data/private/sharepoint-session.json`; ingestion worker only |
| Refresh official and public sources together | `.\refresh-scrapers.cmd --rules-only` (add `--watch` for hourly refresh) | Both snapshots below, kept separate |
| Scrape official notices once | `.\refresh-notices.cmd --rules-only` | Private raw scrape, official snapshot, reviewed closure output, unresolved-review output |
| Keep official notices current hourly | `.\refresh-notices.cmd --rules-only --watch` | Same snapshot; keep this worker running in a separate terminal |
| Scrape public feeds once | `.\refresh-reports.cmd --rules-only` | `data/private/external_reports.json`; `/external-reports` and `/external-reports/status` |
| Keep public feeds current hourly | `.\refresh-reports.cmd --rules-only --watch` | Same public-report snapshot |
| Start the integrated app | `.\start-server.cmd` | [Campus map](http://127.0.0.1:8000), [API docs](http://127.0.0.1:8000/docs), [backend diagnostics](http://127.0.0.1:8000/backend) |

The frontend polls `/closures` every 15 seconds and source/upcoming metadata every minute.
Polling reads saved data; it does not trigger external scraping. The worker's `--watch`
interval defaults to an hour. Map import and graph rebuilding are explicit commands.

Official scrape order: **live SharePoint → last complete scrape → spreadsheet fallback**.
A failed refresh preserves the previous published snapshot and marks source status. Partial
pagination is rejected. Notice dates/times are interpreted in America/New_York then stored
with timezone information. `last_confirmed` on official data means **source observed**, not
a physical inspection. For community data it means report/confirmation receipt time.

The live scrape checked during integration read 1,095 distinct notices. It published two
upcoming degraded elevator-inspection notices for November 17, 2026: Patterson, 8–10 a.m.,
and Grayson, 10–11 a.m. Eastern. There were no active mapped closures at that check and one
unresolved notice. These are observations from that refresh, not fixed application data.
Use `/closures/status` for current counts and source timestamps.

The latest successful live SharePoint check was **November 14, 2026 at 1:17 a.m. Eastern**.
An earlier expired-session HTTP 401 correctly used the last successful scrape, not the
spreadsheet. The operator then saved a new verified session into this workspace and live
ingestion resumed. Helper v5 checks actual item access with both the browser and restored
session before reporting success. PVTA and Collegian were also refreshed live at that check.

## What we still need from better coverage

- Verified door approach geometry, curb cuts, surface conditions and measured slopes.
- A floor-aware indoor graph connecting actual elevator stops and entrance levels before
  claiming real elevator-outage rerouting.
- Reliable elevator identifiers and floors served to disambiguate multi-elevator buildings.
- Reviewed location/time evidence before promoting social/news reports to closures.
- Role 4's shared Atlas-backed report store and agreed conflict policy for deployment.
- An approved background-service identity for unattended SharePoint ingestion. The present
  operator browser session expires; teammates must use their own authorized account.

Secrets belong only in backend `.env` and ignored private files. Do not share session cookies
or put Gemini/Reddit/Facebook credentials in frontend `VITE_*` variables. Gemini is a parser,
not a source of campus facts; route summaries currently use deterministic templates.

The [2024 accessibility PDF](https://www.umass.edu/planning-design-construction/sites/default/files/2024-11/CampusMap-Accessbility-Large-2024.pdf)
and [ILC building page](https://www.umass.edu/planning-design-construction/book/integrative-learning-center-2014)
were supplied as references. They are **not currently ingested automatically**. Additional
ArcGIS parking/restroom layers are also not yet imported. We should only advertise a source
as active after its fetch and normalized output have been checked.
