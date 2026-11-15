# Guided library–ILC navigation: Role 1 and Role 3

The backend implements the conversation and routing sequence you described:
identify a starting place → elevator and exit → outdoor walk → confirm arrival →
ask whether to continue inside → entrance, elevator and destination.

**Real ILC and library indoor routes are not enabled yet.** The live scraper collects
real place references; those references do not specify every walkable connection. The
backend returns `coverage_unavailable` when the necessary reviewed graph is missing.
The complete working example uses explicitly fictional layouts in `examples/navigation/`.
No frontend or Role 4 implementation is part of this addition.

For the whole application, read [APPLICATION_GUIDE.md](APPLICATION_GUIDE.md). For what
the public interactive map actually contains, read [INDOOR_SOURCE_AUDIT.md](INDOOR_SOURCE_AUDIT.md).
For the separate data service's schema and remaining integration requirements, read
[BACKEND_HANDOFF.md](BACKEND_HANDOFF.md).

## The user flow

| Situation | Backend behavior |
| --- | --- |
| No starting location | Asks which pilot building the user is in; coordinates can identify an outdoor start |
| “Second floor of the library” | Recognizes library and floor 2, then asks for a mapped room, entrance or elevator landing |
| “Elevator A” without a floor | Asks which landing if the label identifies multiple floors |
| Exact start and destination room | Plans the entire indoor/outdoor/indoor journey |
| Exact start and destination “ILC” | Plans to the outside approach of an eligible reviewed entrance and returns an arrival prompt |
| User confirms arrival | Asks whether to finish outside or select a destination inside |
| User chooses an indoor destination | Reads closures again and routes through an eligible entrance and elevator |
| Elevator unavailable | Chooses another mapped feasible connection or returns `no_route`; preferences are not relaxed |
| Room exists in a directory but is not mapped | Explains the coverage gap without generating directions |

A floor is not an exact starting position. The server cannot know where someone is relative
to a doorway or lift from “floor 2.” It asks for a known landmark instead of placing the user
at an assumed elevator. There is no indoor GPS or automatic arrival detection.

## API handoff

Start with `.\start-server.cmd`. Open <http://127.0.0.1:8000/docs> and look under
**Guided navigation**. Expand an endpoint, click **Try it out**, enter JSON, then **Execute**.
The current React map does not call these endpoints yet.

| Endpoint | Purpose |
| --- | --- |
| `GET /navigation/catalog` | Library/ILC coverage, floor labels, reviewed landmarks and scraped references |
| `POST /navigation/resolve` | Resolve a description or return a clarification/coverage result |
| `POST /navigation/plan` | Ask for missing locations or plan a journey |
| `POST /navigation/arrive` | Confirm the outside arrival position, ask about going inside, then plan the continuation |

These requests are stateless. The client retains the user's answers, preferences and the
returned `arrival_context`, and resends them on the next call. A question's `field` identifies
the value to fill; `choices` contain identifiers to select. Choosing a different building
should clear the old floor/node selection and replace conflicting text.

Ask about the starting floor:

```json
{
  "origin": {"text": "second floor of the library"},
  "destination": {"text": "ILC"},
  "no_stairs": true,
  "max_grade": 5
}
```

Send this to `/navigation/plan`. It returns `needs_input` with `code: choose_landmark`.
With the current draft campus maps, `coverage.routable` is false and the list of reviewed
landmarks is empty. A source reference is not a selectable routing node.

Once reviewed maps exist, supply the chosen `origin.node_id` from the catalog or question
choices. Do not use the fictional node IDs from the demo against the production server.

The `LocationQuery` format supports either indoor fields or outdoor coordinates:

```json
{"outdoor": {"lat": 42.391, "lng": -72.528}}
```

Indoor fields are `text`, `building_id`, `floor_id` and `node_id`. The pilot IDs are `library`
and `ilc`. The resolver recognizes building aliases, numbered/ordinal floor descriptions
and reviewed landmark aliases. It uses deterministic matching; Gemini is not involved in
location resolution or path selection. It never derives a floor from a room number.

When a route to a building is ready, its response includes:

```json
{
  "arrival_context": {"building_id": "ilc", "portal_id": "ID_FROM_REVIEWED_MAP"},
  "arrival_confirmation_required": true
}
```

Send those exact values to `/navigation/arrive`. With `confirmed: false` or omitted, the
backend asks the user to confirm the mapped outside approach. With `confirmed: true`, it
asks whether to continue inside. A subsequent request can look like this:

```json
{
  "building_id": "ilc",
  "portal_id": "ID_FROM_REVIEWED_MAP",
  "confirmed": true,
  "continue_indoors": true,
  "destination": {"text": "N211"},
  "no_stairs": true,
  "max_grade": 5
}
```

`ID_FROM_REVIEWED_MAP` is a placeholder, not a working campus entrance ID. With
`continue_indoors: false`, the result is `arrived` with scope `outside_entrance_approach`.

Omit `closures` or set it to `null` to read the existing server closure snapshot on each
route calculation, including arrival. An explicit array overrides that snapshot;
**`"closures": []` intentionally means no closures** and is useful only when the caller
really wants that behavior. Missing required snapshots produce HTTP 503. Stale snapshots
carry freshness metadata and a route warning. The service does not write reports or a database.

Carry the same preferences into `/navigation/arrive`; defaults apply if they are omitted.
Supported fields are `no_stairs`, `max_grade`, `allow_unknown_access`, `allow_unknown_grade`,
`need_automatic_door`, and `min_width_m`. Strict defaults reject unknown indoor access/grade.

## Results and instructions

| `status` | What the caller should do |
| --- | --- |
| `needs_input` | Display the question and choices, then resend the updated request |
| `route_ready` | Display the ordered stages and associated route geometry |
| `coverage_unavailable` | Explain the missing map coverage; offer the existing outdoor planner separately |
| `no_route` | Explain that no mapped route meets the requested constraints and closures |
| `arrived` | Finish the trip at the stated scope |

These workflow results use HTTP 200. Malformed requests use HTTP 422; unavailable required
infrastructure uses HTTP 503. Lower-level `/indoor/route` and `/journey` retain their original
HTTP error behavior.

`route_ready` includes `journey`, `stages`, `closure_context` and positioning information.
Stages occur in traversal order: `leave_building`, `outdoor`, `enter_building`,
`inside_destination`. A phase can appear more than once because an indoor leg and an
entrance-approach leg are distinct. Each stage includes `instructions` and the original `leg`.
Outdoor and entrance geometry is geographic; indoor geometry uses its declared floor-local
coordinate system. Do not plot image pixels as latitude/longitude.

The initial building-only trip stops **outside** the chosen entrance. Arrival confirmation
does not assume the door was crossed. The continuation recomputes from that exact outdoor
graph node and can choose another entrance if closures have changed.

For “second classroom on your right,” the map supports reviewed `maneuvers` with a
`from_node → via_node → to_node` sequence, instruction text, source and evidence. The cue
is used only when the actual route follows that approach. It does not reverse automatically
and cannot replace an elevator transition. Generic directions remain the fallback.

## Role 3: turning sources into usable places

Run `.\refresh-indoor.cmd` to fetch six public sources. The latest successful refresh collected
155 references: 27 library service/floor records, 26 library floor images, 24 Campus Center
room records, 16 ILC classrooms, 57 library/ILC restrooms, and 5 ILC study spaces.

The scraper preserves source IDs, observation dates, raw floor labels and relevant attributes.
It checks pagination and geographic coordinates and retains the previous complete source
when a fetch fails. Records remain `routing_eligible: false`. A refresh never replaces a
manually edited draft or reviewed map.

To connect these sources to the router, map nodes may include `source_record_ids`. Those
are explicit reviewed links from a source room/landmark to a physical graph node. A source
match can resolve to a node only after this connection or a reviewed label/alias exists.
Several matches trigger clarification. A source point is never snapped automatically through
walls to the nearest indoor node.

Before publishing either pilot, map the entrance thresholds, walkable corridors, room doors,
actual elevator stops and outdoor approaches; document access, grade/scale and source evidence.
The [indoor import workflow](INDOOR_MAPPING.md#turn-a-floor-plan-into-a-routing-map) validates
and publishes that graph. Library images are available; a usable current ILC floor plan and
documented connectivity are still missing from the sources checked.

## Offline demonstration and validation

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_navigation
.\.venv\Scripts\python.exe -m pytest -q
```

The demonstration prints a floor clarification, a route to an entrance, an arrival question,
and an indoor detour that switches from fictional elevator A to B. Its files under
`examples/navigation/` show request/response contracts. The synthetic fixtures are created
in memory, never published to `data/indoor/`, and are rejected by production indoor routing.

Backend validation passed **186 Python tests** and Ruff. Tests cover the staged trip,
ambiguous positions, floor conflicts, refreshed closures, blocked elevators/entrances,
direction-specific cues, source pagination and complete-cache fallback. No frontend files
were changed or frontend tests run for this addition.
