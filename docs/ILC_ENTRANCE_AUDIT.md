# ILC entrances: source evidence and remaining connections

Checked the public UMass Entrances_PNTS records and OSM on 15 November 2026.
All three UMass records document a door opener, all-floor access, and no keycard
requirement. Their edit date is **26 July 2019**, and they do not specify entry
floor. These records describe historical equipment, not current operation.

Update, 15 November 2026: the user confirmed that their friend saw or used a
push-button opener at the **southwest doorway entering floor 2**. This peer
report independently supplies opener evidence for `osm-entrance-6382267406` and
the `ilc-southwest-floor-2` portal. An operating test and the observation date
were not specified. The saved report is in
`data/reviews/entrance-observations.json`; it does not certify the whole route.

| Entrance | Evidence found | Required to enable continuous routing |
| --- | --- | --- |
| North | UMass record [55](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances_PNTS/FeatureServer/0/55), plus north vestibule on the floor-1 plan | Match the exterior threshold, the GIS opener record and an actual outdoor path. The existing indoor landmark is inside the vestibule, not an outdoor graph node. |
| Southwest | UMass record [56](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances_PNTS/FeatureServer/0/56); [OSM doorway 6382267406](https://www.openstreetmap.org/node/6382267406) says level 2 and matches the floor plan; peer confirmation now identifies a push-button opener at that doorway | Opener evidence is now linked. Keep the final edge's 6.5% terrain estimate until better slope evidence is available. The frontend default is now 7%, as requested; lower user-selected limits still apply. |
| Southeast / North Pleasant Street | UMass record [57](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances_PNTS/FeatureServer/0/57); [OSM doorway 6382267407](https://www.openstreetmap.org/node/6382267407) says level 2 | Current OSM attaches this node only to the building outline, with no walking way. Establish the external approach and trace the floor-2 vestibule-to-corridor connection. |

The southwest GIS point and OSM doorway are several meters apart. The official
record has no floor field, so matching only by compass direction/proximity could
attach an opener to the wrong door or level. Preserve the two geographic
identities; the southwest portal now uses the independent peer report. The
southeast doorway is missing from the routing
graph because it lacks a walking connection, not because it lacks a building tag.

To complete each join, record the specific exterior door, entry-floor sign,
opener button, and the path leading to it. Check steps and slope along that path.
Then attach the source IDs to one doorway, trace the inside corridor in the plan
coordinate frame, publish its outdoor/indoor portal and test both travel directions.
A photo/marked plan or current facilities record can establish identity; slope
needs appropriate measurement or reliable source evidence. Do not replace missing
connections with a straight line through an unknown area.

Sources are saved under `data/plan_wayfinding/sources/ilc/`:
`entrance-records.json`, `osm-building.osm`, `southwest-ways.osm`,
`southeast-ways.osm`, and the two original floor mosaics. Run
`python -m scripts.audit_ilc_entrances` to rebuild
`data/reviews/ilc-entrance-audit.json` from those snapshots and the current graph.
This audit is an input for review; it does not automatically enable candidate doors.

`campus_routing/entrance_observations.py` applies peer evidence only to the exact
building, entrance ID, floor and recorded coordinate. It runs when routing reads
the catalog and after `scripts.refresh_entrances` supplements scraped records.
Scraper refreshes therefore retain the confirmation. It changes door equipment
metadata without modifying slopes, access restrictions or graph geometry.

The old building-user-manual URL currently redirects to the PDC homepage, so it
was not used as evidence for these joins. No UMass sign-in was required for the
GIS or OSM records above.
