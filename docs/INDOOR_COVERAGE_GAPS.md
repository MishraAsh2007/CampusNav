# What remains for Oak, Campus Center and Student Union

The backend can route over additional explicitly mapped hall/door connections and
elevator landings. Completing every building still requires tracing the available
circulation and finding the missing connections. Not every unfinished destination
is blocked by a missing source; the currently implemented scope is bounded.

| Building | Current gap | Work needed |
| --- | --- | --- |
| Oak | 34 first-floor wing landmarks have local hall paths but no mapped step-free connection to the exit lobby. | The inspected `707-01` plan draws stairs/level changes near the lobby approaches. Identify a documented step-free bypass or another usable exit and its approach. Then add only those connections and check both directions. Upper-floor-to-lobby paths already exist. |
| Campus Center | The floor-2 concourse now connects to selected foyers on 1 and 8–11. Further circulation is untraced and other floors lack plans in this source set. | Trace additional source-supported circulation, obtain missing-floor plans and complete outdoor entrance alignment. The new bank approach is an approximate landmark, not a surveyed car door. |
| Student Union | Current routing is a landmark sequence to Gallery 235, not a whole-building graph. | Obtain a post-renovation plan with shared halls, doorways, elevator landings and entrances; trace it and reconcile the numeric floor labels. The old third-floor ballroom image cannot establish current circulation. |

The [Hospitality page](https://umasshospitality.com/locations-capacities) links the
Campus Center images. Its Student Union image shows the ballroom on floor 3.
[UMass's renovation announcement](https://www.umass.edu/news/article/video-student-union-closed-major)
states that most interior walls were to be repartitioned and the ballroom moved
one floor higher. That is why the older image is retained as a reference rather
than used to connect today's Student Union rooms.

## Results of the additional search

**Campus Center: one gap resolved.** The
[2026 conference program](https://bpb-us-w2.wpmucdn.com/wordpress.amherst.edu/dist/1/251/files/2026/03/MAA_2026_Final_Program.pdf)
labels the floor-2 elevator core and the floor-11 bank on PDF page 31 (printed page
30). [Hotel UMass's current FAQ](https://hotelumass.com/faq) also directs visitors
from the concourse to the upstairs hotel lobby using elevators. The annotation
corroborates the core location on the existing Hospitality image. The source-based
graph now connects the concourse bank approach to the existing modeled event-floor
bank. All 31 Campus Center landmarks reach the audit target in both directions.
This documents bank alignment, not individual car identities or physical access.
No stop on an otherwise missing floor is added.

The PDF edition is hash-pinned before its annotated position can enable that
connection. A changed edition must be reviewed. Run `scrape-all.cmd --rules-only`
to collect the sources, then `python -m scripts.build_campus_center_plans` using
the project virtual environment to regenerate the authored map. Scraping alone
does not rewrite the route graph.

**Oak: unresolved.** A second accessible SharePoint file,
`Oak_1_010125.pdf`, was found in the archive/reference folder and compared visually
with `707-01.pdf`. Its title block still states February 20, 2014; the filename is
not evidence of a January 2025 drawing revision. It also shows the first-floor
stairs near the lobby. It does not document the missing step-free bypass, an
alternative usable exit, or another elevator landing connection. Those 34 wing
landmarks remain disconnected from the modeled exit target.

**Student Union: unresolved.** Additional sources inspected include the current
[architect project page](https://shepleybulfinch.com/projects/university-of-massachusetts-student-union/),
the design-award page, the architect's post-occupancy study announcement, the
authenticated SORC planning-resources page and more targeted SharePoint searches.
No usable post-renovation circulation plan was obtained from these sources.
Photos, renderings and room seating layouts do not supply the missing connections.

The official UMass project pages link two-page sustainability brochures for
[Student Union](https://www.umass.edu/planning-design-construction/book/student-union-renovation-2020),
[the Honors complex](https://www.umass.edu/planning-design-construction/book/commonwealth-honors-college-2013)
and [Campus Center dining](https://www.umass.edu/planning-design-construction/book/lincoln-campus-center-dining-renovations-2014).
All three SharePoint brochures were downloaded successfully using the saved UMass
session and inspected. They contain building/project context, not interior route
plans. The unified collector now refreshes them under `building-documents`.
Private manifests and the alternate Oak source reference are included in the
private collection bundle; raw page canvases and authentication state are excluded.

## SharePoint investigation

The saved UMass session successfully accessed SharePoint search on November 14,
2026. Exact-building drawing searches returned 138 Student Union references and
219 Campus Center references; these are search hits, not 357 floor plans.
The inspected 2026 event-planning PDF directs organizers to room seating diagrams.
The public Student Union ArcGIS feature layer contains a building polygon with
no floor/corridor fields. Neither supplies the missing interior circulation.

Listing the Student Affairs design parent folder returned HTTP 403, while search
and a specific event PDF returned HTTP 200. A working login does not imply access
to every document folder. Repeated sign-in is not the remedy for that result.
No additional account permissions were requested or changed.

Repeat the authenticated metadata search:

```powershell
.\.venv\Scripts\python.exe -m scripts.search_central_plans --building student-union
```

Results go to `data/private/central-plan-search.json`. This searches indexed
documents visible to the account; it does not prove that other UMass plans do not
exist. Search results are not automatically imported as walkable routes.

## Library source work

See [library elevator coverage](LIBRARY_ELEVATOR_COVERAGE.md). The additional
public scraper collects floor-local elevator regions and historical car references.
The owner's current report is five cars serving all floors. Old express/local
restrictions are not applied to current routing. This source work remains separate
from the teammate's ground-truth JSON for a later explicit merge.
