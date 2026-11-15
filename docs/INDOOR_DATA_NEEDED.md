# Indoor route verification: findings and missing evidence

Checked November 14, 2026. See [the exhaustive floor audit](INDOOR_COVERAGE_AUDIT.md)
and its JSON for per-destination results.

## What the routing check establishes

The audit now also closes each mapped elevator asset in turn for every destination.
ILC retains all 16 destinations after either individual elevator closure; with both
closed, only seven first-floor destinations remain reachable. Du Bois currently has
one modeled elevator asset; closing it removes all 27 destination routes. No audit route
used a closed elevator or silently substituted stairs. The Du Bois result identifies
a data limitation: the map needs the actual independent elevator banks and stops before
it can represent a verified alternative elevator route. Tests establish modeled behavior,
not the real number or operating state of elevator cars.

All 16 mapped ILC destinations and all 27 mapped Du Bois destinations have a route
from at least one mapped entrance and a route back under the default step-free
preferences. This checks every mapped destination, rather than two sampled rooms.
It does not verify that graph edges follow physical corridors or that an elevator
actually serves every modeled stop.

| Building | Coverage now | Missing evidence |
| --- | --- | --- |
| ILC | Floors 1–4 represented; 7 destinations on floor 1, 7 on floor 2, 2 on floor 3, none on floor 4 | Actual floor 3/4 plans, floor 4 destinations, complete room directory and documented elevator stops. Floors 1/2 have plan assets but their trace/door alignments still require checking. |
| Du Bois | 27 floor records: lower level and 1–26; 27 service destinations | Third-floor plan; confirmed E/LL/numbered-floor correspondence; actual room/door/corridor geometry and elevator stops on every floor. First-floor map has no destination node; two service destinations currently map to LL. |
| Brown | Nine-floor corrected draft and existing historical candidate traces | Suite entrance and internal-door traces, metric calibration, elevator stops, entrance-floor alignment and resident/keycard permissions. No real route enabled. |
| Other residences | Private source/review workspaces for the downloaded building set | Same per-building tracing and access evidence. Drawings are acquired; navigable topology remains unfinished. |

Du Bois floor 3 is identified as staff offices in the public service directory. A
directory listing is not permission to route visitors into staff space. Access to such
destinations must be checked before publishing them as public routes.

The existing library floor count and ILC classroom count must not be advertised as
complete, physically verified room coverage. Several current destinations stand for an
entire service/floor, rather than a surveyed doorway. Existing pilot metadata uses
`reviewed`, but this audit does not establish facilities or field review of those routes.

## SharePoint access result

### User-supplied Payette PDFs checked

`Integrated Sciences Building - Payette.pdf` and
`Integrated Sciences Building - Payette-4.pdf` were inspected. They are five-page
printouts of https://www.payette.com/project/umassamherstisb/, with level-three and
level-four plan views respectively. Their title and project description identify
the **Integrated Sciences Building (ISB)**, not the **Integrative Learning Center (ILC)**.
UMass's building-address directory lists them separately (ISB: 661 North Pleasant
Street; ILC: 650 North Pleasant Street). These drawings were therefore excluded from
the ILC map; they do not fill its missing third/fourth-floor plans. Original PDFs
remain in Downloads and no routing geometry was changed.

The saved UMass session successfully read the residence floor-plan folder (HTTP 200).
No password is needed in chat. The folder exposes Orchard Hill, CHCRC, Sylvan, Southwest,
Central, Northeast and North Apartments. Those plans are already downloaded privately.

Authenticated search requests for ILC and Du Bois plan/manual PDFs also succeeded, but
the returned candidates were planning reports, presentations and meeting archives;
they did not identify a usable missing floor plan. This does not prove the plans do
not exist: SharePoint only searches indexed documents visible to this account.

The check can be repeated with:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_plan_access
```

Results, including candidate paths, stay in the ignored
`data/private/residence_floorplans/access-check.json` file.

## What you can obtain

The most useful next item is a **direct SharePoint folder or document link** from
Facilities/Space Management containing ILC floor 3/4 plans and Du Bois floor 3. A
link to the actual document library is more useful than another password: account
sign-in alone does not establish document permissions or discoverability.

For Brown, ask for the elevator's served-floor list and which first-floor door matches
the accessible entrance on the campus map. For all residences, ask whether the plans
can be used to publish interior navigation, which corridors/doors require resident
access, and whether dimensioned/as-built drawings or measured routes are available.
No facilities request has been sent on your behalf.

## Corrections made during this pass

- Brown's default builder now creates a source-only corrected draft instead of projecting
  labels into invented doors with an unsupported meter scale. Earlier traces are preserved.
- Automatic Brown entrance/elevator inference now stops with an explicit explanation.
- The ILC tracing script no longer labels untraced floors 3/4 as traced against floors 1/2.
  Existing affected third-floor evidence was corrected; the pilot geometry remains flagged.
- The library's generated `3rdth Floor` display label was corrected to `3rd Floor`.
- Added repeatable all-destination forward/return graph coverage checks.

These fixes do not finish real dorm topology. Publishing a complete route requires the
missing physical connections to be traced and reviewed, rather than changing a draft's status.
