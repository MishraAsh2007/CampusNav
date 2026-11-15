# Automatic-door evidence and remaining gaps

The outdoor catalog originally consumed only the public `Entrances` layer used
by the Campus Accessibility web map. A second public UMass layer,
`Entrances_PNTS`, contains powered entrances absent from that layer, including
records already cited by the indoor ILC and library portal data.

## Sources and interpretation

- [Campus Accessibility map](https://www.arcgis.com/apps/instant/basic/index.html?appid=4575634567794afd863c83bc4d6d6d4a):
  the [Entrances layer](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances/FeatureServer/0)
  contains 215 records at collection. UMass labels this map August 2022.
- [Supplementary public UMass item](https://www.arcgis.com/home/item.html?id=88ffb7cddec243b9b6cebe80ccde1416):
  the [Entrances_PNTS layer](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances_PNTS/FeatureServer/0)
  contains 279 records at collection. The added records have last-edit dates of
  July 26, 2019. These are historical records, not field confirmation in 2026.
  `hasAutoDoorOpener=1` is stored as `push-button`; `isKeyCardRequired=0` marks
  public access in the source. `isAccessible` and `isAccessibleToAllFloors` are
  retained as source evidence rather than inferred from the presence of an opener.
- [Building footprints](https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/BuildingData/FeatureServer/0)
  associate points to buildings. The association checks all footprints, not just
  the buildings selected for the app. Ambiguous points are withheld.

## Catalog additions

| Building | Additional powered entrance records | Qualification |
| --- | --- | --- |
| ILC | 55, 56, 57 | Three historical public powered entrances |
| Du Bois Library | 80 | One historical public powered entrance |
| Student Union | 84 | Historical record predates the renovation; current location/operation needs confirmation |
| Old Chapel | 279 | Service OBJECTID_1=279, original OBJECTID=293; opener and all-floor access documented |
| Campus Center | No additional record accepted | Existing 2022 records 179/180 remain; newer nearby records take precedence |
| Goodell | None accepted | Additional entrance-specific evidence still needed |

The stable supplemental IDs are `umass-legacy-entrance-<OBJECTID_1>`.
Records 56, 57 and 80 match the coordinates and source OIDs already cited by
existing indoor portals. Those indoor nodes now explicitly reference these IDs.
This does not bypass the separate check that an outdoor route actually reaches
the declared portal anchor. No new indoor corridors or nearest-door joins are inferred.

## Refresh and audit

```powershell
python -m scripts.refresh_entrances
# Or as part of the unified collector:
.\scrape-all.cmd --rules-only --stage entrance-evidence
```

The normal full collector runs `entrance-evidence` after `building-catalogs`.
It refreshes both public catalogs without rewriting residences, and saves
`data/entrance_evidence.json` with source dates, selected source fields and every
matching decision. The combined public collection includes that evidence.
Fetch failures retain the last successful files; fetched times are never labeled
as physical confirmation. The primary layer wins whenever a legacy point is
within 8 metres of a primary point. Older conflicting records do not enable a door.

## Routing checks and limits

Local real-graph tests on November 15, 2026 produced Student Union-to-library,
Student Union-to-ILC, and library-to-Old Chapel routes with automatic doors
required, stairs blocked and maximum grade 6%. Each selected historical door
adds a visible warning about the age of its evidence and unverified operation.

Campus Center-to-ILC/library still failed those preferences using the documented
powered entrances. Finding a door does not establish a usable outdoor approach:
slope, steps, closures, graph connectivity and exact indoor thresholds remain
independent checks. This update does not claim automatic-door coverage for every
building, nor that a documented opener is currently functioning.
