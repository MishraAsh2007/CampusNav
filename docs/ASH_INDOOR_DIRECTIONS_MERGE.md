# ash/indoor-directions comparison and merge

Compared our `248f20e` with `ash/indoor-directions` at `16ab354` on November 15,
2026. The shared ancestor is `f73e8fc`, already imported through Ash_ver.
This branch adds seven frontend files/changes; it adds no newer floor plans,
building coverage, elevator evidence, routing backend or scraper data.

## What was missing and is enabled now

| Addition | Current result |
| --- | --- |
| Outdoor guided mode | **Start guided directions** opens a compact card and hides the trip planner. Close returns to the existing draggable planner. |
| Spoken outdoor steps | Voice is on by default with a mute toggle. Next/Back speak within the tap event for phone browsers; GPS advancement speaks the new instruction. |
| Optional GPS progression | **Follow me** requests outdoor location and advances near maneuver coordinates. Manual Next/Back remain available. |
| Off-route prompt | A recent accurate fix continuously outside the route tolerance for ten seconds offers **Reroute from here**. The user's routing preferences remain in force. |
| Map follow and arrival | The current instruction pans the map and updates the same selected-step marker used by the existing directions. At a matched accessible entrance, **Go inside** opens our existing indoor flow. |
| Ash indoor text directions | A capability-gated panel supports arriving/leaving via `/api/indoor-route` when a separately configured indoor server offers that endpoint. The current integrated server uses our existing plan-wayfinding guide. |

## Merge adjustments

- Ash's GPS helper indexed steps by GeoJSON feature. Our backend can return one
  feature with many maneuvers. `services/outdoorProgress.ts` projects each actual
  maneuver onto the route, clips projections to the search interval, and does
  not connect disjoint features with invented segments.
- GPS advancement requires a fix no older than 15 seconds with reported accuracy
  of 25 m or better. Arrival also requires proximity to the actual endpoint.
  Poor fixes leave manual controls available. The blue dot still identifies the
  selected instruction; this merge does not add an independently drawn GPS dot.
- New routes reset to their own instructions; previous geometry is not reused
  while a request is pending. The guide displays a loading state during rerouting.
- The existing mobile sheet, map rendering stability, three ILC map choices,
  upper auditorium, corrected restroom outlines and hall bends are preserved.
- The alternate indoor panel rejects a substituted doorway when the API returns
  a different entrance/exit from the outdoor endpoint. It filters expired reports,
  prevents stale requests from replacing newer ones, uses 16px search text, and
  labels unblocked elevators **No blocking report** rather than claiming working
  status without an operating check.

## Retained separately

`components/indoor/engineRoute.js` is imported from Ash as a standalone adapter
for his `status: engine` map contract. It is not installed into the active
`IndoorFlow.jsx`: our exact-node, exact-portal and drawing-based routes remain in
that flow. Ash's alternate engine still has the documented constraints and gaps
in [ASH_VER_MERGE.md](ASH_VER_MERGE.md), including nominal indoor measurements,
placeholder floors and partial-bank outage semantics. No extra indoor GPS or
untraced floor coverage is claimed by this merge.

## Checking the result

1. Open the local application and request an outdoor route.
2. Choose **Start guided directions** on the direction card.
3. Use Next/Back, toggle voice, and close the guide to return to trip details.
4. On a trusted HTTPS phone preview, choose **Follow me** to test outdoor GPS.
5. At the matched ILC southwest entrance, choose **Go inside** and check the
   existing indoor guide and all three map styles.

Frontend checks cover GPS projection with one feature/many maneuvers, missing
coordinates, disjoint features, stale/imprecise fixes, arrival, pending routes,
and exact-door preservation. Device GPS and spoken output still need an on-site
phone test; unit tests simulate location fixes.

Validation at merge: **39 frontend tests passed**, TypeScript and the production
build passed. The current ILC data, IndoorFlow, map-style components and Leaflet
renderer were compared byte-for-byte with the pre-merge versions and preserved.
