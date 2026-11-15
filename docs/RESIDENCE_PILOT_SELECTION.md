# Choosing a residence pilot by evidence, not by how much code exists

**Latest selection:** [Oak Honors shared-hall elevator pilot](OAK_HONORS_PILOT.md)
implements the clarified room-exterior starting point and a floor-2-to-floor-1 elevator
sequence. The Brett discussion below records the earlier same-floor option.

Brown is no longer the preferred navigation pilot. Its private trace is retained as
mapping work, but its suite connections, metric scale and elevator/entrance alignment
prevent it from being presented as completed navigation.

## Sources compared

The residence inventory contains 51 distinct buildings. Matching the public ArcGIS and
OSM records found sourced entrance positions for 23 of them; the other 28 only have outdoor
network meeting points. No building in the records examined has a complete set of
confirmed current entrance access, elevator served floors, indoor doorway clearances,
walking grades and public/resident permissions. The accessibility-map edition is August
2022. A map point labeled accessible does not prove that every indoor connection works today.

Three drawing sets were inspected to choose a smaller task with fewer unresolved dependencies:

| Candidate | Evidence available | Why it is or is not the next pilot |
| --- | --- | --- |
| Brett | Official first-floor plan with direct room-to-hall doors and a continuous west-wing hall; sourced accessible entrance point | Selected for **same-floor room-to-room** wayfinding, avoiding unknown elevator stops and entrance alignment |
| North A/B/C/D | Two sourced accessible/keycard entrances per building, first-floor and grouped upper-floor plans; outdoor round trips meet the tested 5% limit | Good next candidates for entrance/lobby work; apartment suite connections, geographic doorway alignment and actual elevator stops remain unresolved |
| Elm | Public accessible entrance record, elevator positions, and plans starting at floor 3 | Entrance-level correspondence must be established before claiming an outdoor-to-room route |

This is not a claim that all 51 drawings have been manually traced. Source matching and
outdoor coverage were checked across the inventory; the three alternatives above were
compared visually for the next indoor pilot.

## Implemented Brett scope

The first-floor west-wing segment connects the visible thresholds of Rooms 101–109 and
111, with Rooms 102/104/106/108 on the opposite side of the hall. There are 10 selected
room thresholds and 8 hall junctions, connected by 17 drawing edges. Other rooms, floors,
elevator rides, exterior entrances and outdoor portals are outside this pilot.

`campus_routing/plan_wayfinding.py` provides a qualitative same-floor path over those
connections. It returns **no distance or maximum-grade estimate**. It does not set the
existing measured indoor map to reviewed or claim physical verification. The caller must
explicitly accept drawing-only directions and confirm permission to use the residence
interior; that confirmation is a planning declaration, not an authentication credential.

Exact matched door/hall asset closures can block these paths; expired incidents and incidents
for another building/floor do not. Unmatched/geographic-only reports remain a limitation
and are called out in every result.

## Run the local backend pilot

Prepare the private graph:

```powershell
.\.venv\Scripts\python.exe -m scripts.trace_brett_wayfinding
```

To inspect a room-to-room result when you have permission to use the building:

```powershell
.\.venv\Scripts\python.exe -m scripts.trace_brett_wayfinding --start 101 --end 111 --accept-drawing-only --resident-access-confirmed
```

The generator validates the source PDF hash and stores its source link and drawing-review
scope. Output stays under ignored
`data/private/residence_floorplans/workspaces/brett/first-floor-wayfinding/`.
This is a backend/CLI pilot, not a feature exposed in the current map UI. No frontend
code or production access-control system was added.

Tests cover forward/reverse paths, the drawing-only and resident-permission declarations,
exact door closures, expiration, building/floor isolation and rejection of unmapped rooms.
The full suite passes **214 tests**. This verifies the implemented graph behavior; it does
not convert plan evidence into a current accessible-route guarantee.

## What would enable verified accessible navigation

For the bounded Brett segment, confirm threshold clearance/width, corridor grade and current
resident access. To extend it outside, match the sourced entrance to its actual plan doorway
and trace the approach. To extend it upstairs, obtain the elevator's documented served-floor
list and trace each landing independently. These are narrower checks than Brown's full
suite-to-elevator-to-outdoor pilot and do not require inventing missing values.
