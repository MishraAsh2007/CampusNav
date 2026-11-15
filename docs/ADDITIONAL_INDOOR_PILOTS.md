# Old Chapel, North D and Goodell backend wayfinding

Role 1 builds the graphs and returns directions; Role 3 collects their official
sources through the existing scraper. No frontend code is part of this addition.

**Later integration:** [the updated Role 2 UI](ROLE2_INTEGRATION.md) now consumes
these pilots. The source/coverage limits below still apply.

## Implemented scope

| Building ID | Floors | Connected landmarks | Destinations and limits |
| --- | --- | --- | --- |
| `old-chapel` | 1–2 | 17/17 | Pavilion entry, lobby, common area, conference entrance, auditorium and stage-ramp approach. Basement, tower, restroom interiors and ramp surface excluded. |
| `north-d` | 1–5 | 99/99 | First-floor lobby/shared halls/lounge approaches; 11 apartment approaches per upper floor (03–13), linked through the bank to the lobby threshold. Unknown unit 01, unit 02, bedrooms and unlabeled first-floor east-wing rooms excluded. |
| `goodell` | 3–6 | 70/70 | Selected department/shared-space approaches, including Disability Services, Career Services, cultural centers and Student Success. Individual office doors, other levels and uncertain north bridges excluded. |

Counts mean every **modeled landmark** can reach and return from its audit target.
They do not mean every room is mapped or physical accessibility is verified.
Directions use floor-local coordinates, with `distance_m` and `max_grade` null.
North D now has a separately source-matched southwest threshold through `/journey`;
see [combined indoor/outdoor journeys](DRAWING_JOURNEYS.md). Goodell and Chapel's
outdoor joins remain unresolved. None of these joins are physically surveyed.
The [integrated UI](CURRENT_INTEGRATION.md) can display these scoped indoor routes
and the enabled North D journey when their local private data has been generated.

## Sources and scraper

- **Old Chapel:** [official 2017 renovation page](https://www.umass.edu/planning-design-construction/book/old-chapel-renovation-2017)
  → **Green Building Tour Guide**, rather than the shorter brochure. Page 2 of
  the eight-page PDF contains both main-floor plans. The guide documents the
  elevator and stage ramp; current access and operation need confirmation.
- **North D:** [official North Apartments directory](https://www.umass.edu/living/housing-options/residence-directory/apartments/north-apartments)
  → authenticated residence inventory. `673-01.pdf` covers floor 1, printed
  October 9, 2024 with no revision date. `673-02.03.04.05.pdf` explicitly labels
  floors 2–5 in the drawing, revised September 15, 2026. Its ambiguous `D201E`
  bedroom label is not converted into an apartment-01 destination.
- **Goodell:** [official reopening article](https://www.umass.edu/news/article/goodell-hall-officially-reopens-ribbon-cutting-open-house)
  → original [March 2025 directory image](https://www.umass.edu/sites/default/files/2025-04/Goodell%20Floorplan%20March%202025.jpg),
  5326 × 4013 pixels. [Disability Services directions](https://www.umass.edu/disability-services/about/location-hours)
  corroborate west entry on level 3, east entry on level 5 and elevator travel to
  level 4. Only the repeated red elevator core is linked; white X regions and
  other shafts are not treated as usable elevators.

`campus_notices/building_documents.py` fetches the Chapel guide through the saved
UMass session and Goodell's public original image. A failed source retains its
cached record and observation time. Public Goodell collection can run even if the
private session is unavailable. `campus_notices/residence_plans.py` supplies North D.

`scripts/build_additional_wayfinding.py` contains authored corridor traces.
`campus_notices/plan_integrity.py` pins the inspected source hashes. A changed
edition fails generation before any requested map JSON is replaced. Scraping or
Gemini extraction cannot invent corridors or silently move an old trace to a new
plan. The unified scraper's `additional-wayfinding` stage follows
`building-documents` and rebuilds only the pinned editions.

Sources, cropped floor images, maps and review overlays stay under ignored
`data/private/`. Authenticated PDFs and login/session data are not bundled into Git.

## Prepare and open

With dependencies installed and the saved UMass session, run from the project root:

```powershell
.\scrape-all.cmd --rules-only --stage residence-plans --stage building-documents --stage additional-wayfinding
.\start-indoor-pilots.cmd
```

Open **http://127.0.0.1:8004/docs** and keep the server terminal running.
`GET /plan-wayfinding` lists the pilots. `GET /plan-wayfinding/{building_id}` lists
exact node IDs, source evidence and limitations.

To rebuild from downloaded sources without scraping:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_additional_wayfinding
.\.venv\Scripts\python.exe -m scripts.audit_plan_wayfinding
.\.venv\Scripts\python.exe -m scripts.render_wayfinding_overlays
```

## Try a route

Expand `POST /plan-wayfinding/north-d` in the API docs, click **Try it out**, paste
this body and click **Execute**:

```json
{
  "start_node_id": "apartment-513-5",
  "end_node_id": "exit-threshold-1",
  "accept_drawing_only": true,
  "resident_access_confirmed": true,
  "closures": []
}
```

The result follows shared halls to the elevator, gives one ride from 5 to 1, and
continues through the lobby to its south threshold. It starts outside apartment
D513, with no apartment-interior directions. Swapping the IDs tests the return.
The resident flag is a planning declaration, not authentication.

For public buildings, use the same shape with these IDs:

| Endpoint | Start | End |
| --- | --- | --- |
| `POST /plan-wayfinding/old-chapel` | `entry-threshold-1` | `stage-ramp-approach-2` |
| `POST /plan-wayfinding/goodell` | `east-entry-5` | `disability-services-4` |
| `POST /plan-wayfinding/goodell` | `west-entry-3` | `student-success-east-6` |

They require `accept_drawing_only: true`; no residence declaration is required.

## Outages and handoff

Supply the current `/closures` array in the request. `closures: []` deliberately
tests the graph without disruptions; this endpoint does not fetch closures itself.
Exact bank asset IDs are `old-chapel-elevator-bank`, `umass-elevator-148` (North D)
and `umass-elevator-120` (Goodell). An active `closed` bank closure blocks cross-floor
travel; same-floor routes remain possible. No stairs fallback is used. `degraded`
is a penalty rather than a hard closure. Expired closures are ignored.

Chapel's ID is a drawing-specific logical bank without invented geographic
coordinates or official per-car identity. Role 4 must preserve/resolve exact IDs.
Geographic-only/unmatched notices cannot reliably block these floor-local graphs.
A GIS point does not establish the number or independence of elevator cars.

North D's reviewed source match is implemented in the separate portal registry.
Goodell and Chapel still need exact entrance-to-graph matches. Current door permissions, clearances,
elevator stops/operation and level changes need confirmation before describing
these results as verified accessible navigation. Role 2 can consume the endpoints
later; its frontend was not changed.

## Verification

The audit checks every landmark in both directions. Automated tests cover modeled
floors, API discovery and routes, missing-node rejection, drawing consent, resident
access, ride grouping, closures and expired/other-building reports. Geometric checks
guard key shafts, voids, display cases and uncertain bridges. Private SVG overlays
were inspected for every distinct layout. These are software and source checks,
not a physical survey.

Local acceptance check on November 14, 2026: **258 tests passed**; Ruff passed
for `campus_routing`, `campus_notices`, `scripts` and `tests`. The running port-8004
API returned HTTP 200 for Chapel entry → stage approach, North D floor 5 → lobby,
Goodell east entry → Disability Services, and Goodell west entry → level-6 Student
Success. The unified `building-documents` and `additional-wayfinding` stages
completed as `live` and `derived`. These results apply to the scoped pilots above.
