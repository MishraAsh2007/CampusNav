# Brown: first traced suite-to-exit pilot

This is a private drawing-trace draft for a small connected first-floor area, not
enabled navigation. It replaces the earlier idea of projecting bedroom labels directly
onto a main hallway.

## Actual topology entered

The first-floor trace contains 14 nodes and 13 connections:

Room 107D threshold → shared Suite 107 passage → suite exit doorway → main hall →
lobby double doorway → lobby → inner vestibule door → vestibule → exterior threshold.

A separate branch ends at the lobby approach to the western shaft. That endpoint is
a floor-local junction, not a confirmed elevator stop. No elevator ride or served-floor
connection has been added. The exterior threshold is also floor-local; there is no
assumed geographic entrance or outdoor portal binding.

The source is the authenticated `426-01.pdf` drawing, revised August 21, 2026. Its
checksum is verified against the private workspace before generation. Coordinates
are PDF points in the 792-by-612 drawing space, not latitude/longitude.

## Distance evidence

Three drawing dimensions were compared: 10 feet, 15 feet, and 10 feet 4 inches.
Their scale estimates differ by 8.4%. The drawing is explicitly marked Not To Scale.
The provisional path length is approximately 20.33 meters; this is a drawing-derived
estimate and cannot be treated as a field measurement. The dimension endpoints and
individual conversion factors are stored in the review record for inspection.

Access, walking grades, widths, door operation and threshold clearance remain unknown.
The draft does not label these connections as publicly accessible or step-free. It
cannot be served by the production indoor router or imported as reviewed topology.

## Inspect the result

```powershell
.\.venv\Scripts\python.exe -m scripts.trace_brown_pilot
```

Files are written under the ignored private directory:

`data/private/residence_floorplans/workspaces/brown-house/first-floor-pilot/`

- `map.json`: schema-valid draft graph.
- `review.json`: calibration evidence, candidate path and unresolved requirements.
- `review.svg`: the source drawing with the candidate path and nodes overlaid. Open it
  in a browser and hover over nodes for labels. It was rendered and visually inspected.

This generator recreates its own pilot output; manually edited whole-building maps and
the earlier Brown drafts are separate and are not overwritten.

## Checks and remaining work

The 210-test Python suite passes. Dedicated tests check that the path traverses the suite
and lobby doors in both directions, cutting the suite door disconnects the route, no
bedroom-to-main-hall shortcut exists, and production import/routing reject the draft.
The drawing overlay was checked against the enlarged suite and lobby source views.

To enable real navigation, confirm the visible door thresholds, access rules, clearances
and distances; identify the actual elevator shaft and its served floors; then align the
exterior door with the mapped geographic entrance and trace the outdoor connection.
The next floor trace must be inspected independently rather than copied by room number.
