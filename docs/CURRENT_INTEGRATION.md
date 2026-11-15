# Current map, routing, scraper, and Data API integration

The latest routing/scraper additions are layered on the combined `main` application.
The existing Role 2 UI, MongoDB/Data API bridge, upload endpoints, and explicit demo
mode remain supported. There is one application origin in the standard launcher.

## Start the application

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[pipeline,scraper,data,dev,build]"
npm.cmd --prefix frontend ci
.\start-server.cmd
```

Open **http://127.0.0.1:8000/**. The launcher rebuilds the frontend and starts
`campus_routing.integrated:app`, including the mounted Data API. Use `--memory`
for temporary local storage or `--demo` for the original sample experience.
The normal launcher prefers the expanded outdoor graph, uses the residence
building catalog, and enables locally generated drawing maps and portal records.

Run `.\scrape-all.cmd --rules-only` to collect source families and rebuild
supported derivatives. See [the scraper guide](UNIFIED_SCRAPER.md) for selected
stages and [the README](../README.md) for publication to the shared Data API.
Starting the server alone does not refresh or publish scraper data.

Authenticated plans, browser sessions, and generated private drawing maps stay
under ignored `data/private/`; they are not shipped in Git. Run collection in an
authorized local environment to enable those pilots. The older
`start-indoor-pilots.cmd` is a separate Role 1 diagnostic server on port 8004;
use `start-server.cmd` for the full shared application.

For separate Vite development, the configured proxy also forwards `/journey`
and `/plan-wayfinding`. Separate routing/data/indoor base URLs remain supported.

## Directions and elevator approaches

Outdoor directions appear directly below the trip fields, ahead of preferences,
warnings, and optional narration. The current instruction is always visible, with
Back / Next buttons and an expandable complete list.

Indoor directions use the backend's instructions and path. They include walking
from the selected entrance to the named elevator, riding it to the required
floor, and walking from that landing to the destination. For example, ILC south
entrance to N211 includes a corridor approach and relative turn toward the east
elevator before the ride. The backend derives relative turns only from explicitly
mapped image-plan geometry with a known incoming direction. Source-authored
maneuvers take precedence. Missing corridors are not guessed.

The indoor view keeps its visible current-step panel and optional spoken
instructions. Source-based maps use 2D manual progression; indoor GPS and synthetic
3D views are not offered for these plans. Sample 3D navigation remains available
in explicit demo mode and the separate `/indoor.html` sample.

## Automatic entrance handoff

`POST /plan` may return `indoor_arrival`, joined through declared entrance IDs or
an exact shared outdoor OSM anchor. The selected route must actually reach that
anchor. The UI carries its node, portal ID, and label into the indoor modal.
The `/navigation/plan` flow also retains its exact portal and rechecks shared
closures on `/navigation/arrive` when the user continues inside.

Known arrivals do not require choosing the entrance again. An unknown or ambiguous
join requires a current mapped landmark; no nearest door is silently assumed.
This identifies the planned arrival point, not the user's measured indoor position.

## Complete indoor/outdoor journeys

The optional indoor-start search supports a floor, room, or shared-hall landmark.
Source-based endpoints use `/journey`; its ordered itinerary includes indoor
approaches, entrance transitions, and the outdoor portion. Each indoor leg has a
**View this floor route** control. Swapping a trip also swaps indoor selections.

Drawing routes require acceptance of their limits; residence routes require
permission/keycard confirmation. Unknown drawing distances remain `null`, and
the UI identifies the outdoor distance as a partial total.

North D has a source-matched southwest outdoor threshold. Old Chapel and Goodell
have scoped indoor drawing routes, but their outdoor joins remain unresolved;
requests needing those joins fail explicitly. See [drawing journeys](DRAWING_JOURNEYS.md)
and [additional pilots](ADDITIONAL_INDOOR_PILOTS.md) for exact sources and coverage.

Live routing uses the Data API's authoritative active feed, including drawing
routes. Browser simulations are separate request additions. A changed outage
refreshes an active indoor route from its current instruction landmark. Source
status and public reports awaiting review are visible in the planner; unreviewed
social posts do not become automatic closures.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run test:integration
npm.cmd --prefix frontend run build
```

Tests cover ILC entrance/elevator/classroom instructions, exact arrival handoff,
preservation of backend instructions in the floor view, shared outage handling,
unknown drawing distance, consent, existing report endpoints, and legacy backend
discovery. Floor-plan and facilities gaps remain documented; successful routing
is not a physical-accessibility certification.
