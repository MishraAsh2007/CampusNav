# Expanded indoor wayfinding: Oak, Campus Center and Student Union

Also implemented: [Old Chapel, North D and Goodell](ADDITIONAL_INDOOR_PILOTS.md),
available through the same API and launcher. See that guide for their source collection
and precise floor/destination scope.

These are Role 1/Role 3 backend implementations. Start/end places are in shared circulation,
outside private rooms. They provide source-based wayfinding, not verified accessibility
certification. No new frontend floor view is included.

## What is implemented

| Building ID | Source coverage | Working scope | Limits |
| --- | --- | --- | --- |
| `oak` | All six floor references in five official PDFs; 3/4 explicitly share a template | 258 hall/landing landmarks; floors 2–6 connect through the drawn bank to floor-1 lobby/exit. Reverse trips work. | 34 first-floor wing landmarks remain disconnected from that target because level-change/landing links are unresolved. Those wings have local same-floor paths. |
| `campus-center` | Hospitality images for 1, 2, 8–11, corroborated by a 2026 annotated conference plan and current Hotel UMass directions | 31 selected shared-space landmarks. Floor-2 concourse now connects to the modeled bank and event-floor foyers; reverse trips work. | Bank approach is a landmark, not a surveyed car door. Missing-floor plans, further circulation and outdoor joins remain incomplete. |
| `student-union` | Official Art Gallery accessibility directions | SORC approach → elevators → lower level → Gallery 235 near Craft Center/Black Box Theater; reverse landmark sequence | Text/landmark wayfinding only. No invented corridor geometry, numeric floor labels, whole-building map or exact turns to other rooms. |

Existing ILC and Du Bois graph APIs remain available with their earlier documented pilot
limitations. Additional central buildings were not populated with guessed indoor connections.
Du Bois currently uses one aggregate elevator asset, not individual cars; see
[library elevator coverage](LIBRARY_ELEVATOR_COVERAGE.md) for the effect on outage routing.
The [remaining coverage work](INDOOR_COVERAGE_GAPS.md) separates untraced circulation
from missing source connections and records the authenticated SharePoint investigation.

The [floor coverage audit](EXPANDED_WAYFINDING_COVERAGE.md) exercises every waypoint to/from
the stated target. A successful graph result does not establish current access, clearances,
elevator service or a geographic outside-to-inside link. Distances/maximum grade remain null.

Oak room-associated `near-*` points are positions along explicitly traced shared corridor
centerlines near source room labels. They are not surveyed thresholds. No route segment
enters a bedroom or suite. The floor-1 wings are deliberately separate components rather
than creating a step-free connection over stairs visible near the lobby.

## Source collection and tracing

Public plan collection: `campus_notices/central_plans.py` extracts the unique embedded image
URLs from the [current Hospitality page](https://umasshospitality.com/locations-capacities).
It avoids the misleading page links where several floor anchors resolve to the same URL.
The embedded Student Union diagram is retained as a source reference but not used to assert
current corridor topology: the building was renovated, and the diagram's edition is unstated.

Student Union instructions come directly from the
[official Art Gallery accessibility page](https://www.umass.edu/student-life/student-union/art-gallery/accessibility-contact).
The parser checks for the specific SORC/elevator/lower-level/gallery landmarks before producing
the map. The source's left-turn instruction is relative to its described approach; it cannot
be applied as an indoor GPS turn from any arbitrary position.

Oak drawings stay under the authenticated private residence inventory. Geometry generators
pin the exact reviewed drawing/image hashes in `campus_notices/plan_integrity.py`. A source
refresh with a changed edition requires re-inspection before old geometry can be regenerated.

Prepare/refresh sources and maps:

```powershell
.\scrape-all.cmd --rules-only
.\.venv\Scripts\python.exe -m scripts.expand_oak_wayfinding
.\.venv\Scripts\python.exe -m scripts.build_campus_center_plans --refresh
.\.venv\Scripts\python.exe -m scripts.build_central_wayfinding
.\.venv\Scripts\python.exe -m scripts.render_wayfinding_overlays
.\.venv\Scripts\python.exe -m scripts.audit_plan_wayfinding
```

After the first successful fetch, omit `--refresh` for Campus Center and pass `--offline`
to the Student Union builder to reuse validated cached sources. The public maps are cached
under `.cache/central-plans/`; private graphs and review overlays are under
`data/private/plan_wayfinding/`. None of the private floor drawings are bundled into Git.

## Run and try requests

```powershell
.\start-indoor-pilots.cmd
```

Open <http://127.0.0.1:8004/docs>. Stop an existing port-8004 server before using the launcher.
`GET /plan-wayfinding` lists available buildings, floors, landmark counts and source limits.
`GET /plan-wayfinding/{building_id}` lists exact waypoint IDs and source evidence.
Use `POST /plan-wayfinding/{building_id}` for directions.

Oak, floor 6 to the exit:

```json
{
  "start_node_id": "near-601",
  "end_node_id": "exit-threshold",
  "accept_drawing_only": true,
  "resident_access_confirmed": true,
  "closures": []
}
```

Campus Center: `west-entry-2` → `marriott-foyer`, `near-801` → `marriott-foyer`,
or `west-entry-2` → `u-pub-approach`. Student Union: `sorc-landmark` → `gallery-235`.
Both public-building requests require `accept_drawing_only: true`; they do not require a
residence-access declaration. Oak still requires it as a planning declaration, not an
authentication credential.

Use the current closure feed in real requests. `closures: []` is explicitly a graph-only
test; this endpoint does not fetch disruptions itself. Exact asset IDs are:

- Oak bank: `umass-elevator-183`.
- Campus Center modeled bank: `umass-elevator-141`.
- Student Union gallery elevator group: `umass-elevator-122`.

These IDs join existing source locations; they do not establish car counts or precise
physical bank identity. A matched closed bank removes the ride, without a stairs fallback.
Unknown or unmatched reports remain a coverage limitation. Elevator transitions return
separate floor landing points, not lines crossing floor images. Student Union landmark
steps return null geometry and positions.

## Validation

241 Python tests and Ruff pass. Checks cover six-floor Oak template expansion,
separate floor landings, public-building access declarations, source-gated concourse connection,
room/service-core avoidance on the authored Campus Center traces, source-change rejection,
landmark-only null geometry and valid-map discovery. Exhaustive local graph audits checked
258 Oak, 31 Campus Center and 4 Student Union waypoint results in both directions.

All floor SVG overlays were generated; representative Oak 3/6 and Campus Center 1/8
overlays were rendered and visually inspected. This remains source review, not a field
inspection. Outdoor entrance alignment, operational elevator status and physical access
checks are still needed before claiming a verified end-to-end accessible journey.
