# Demo and submission draft

Working title: Campus Navigation. Intended audience: students and visitors who need to avoid
stairs or steep grades, including wheelchair users, people on crutches, and people with strollers.

## Core story

Campus maps show permanent infrastructure. An accessible trip also depends on what is closed
today. This project combines a walking graph, user preferences, and time-bounded outage data
so a reported disruption can change the route immediately.

## How we built it — implemented work

We built a stateless FastAPI routing service using NetworkX and an OSMnx walking graph for
central UMass Amherst. Terrain elevations provide estimated segment grades. Each request
contains its own closures, which remove or penalize affected edges before Dijkstra runs.

The official-notice connector fetches the authenticated SharePoint maintenance list first,
using a saved scrape and then an exported spreadsheet only as fallbacks. Explicit HTML,
PDF, and text sources are also supported. A deterministic parser handles clear service states and
structured
dates. Ambiguous language can fall back to Gemini with a strict extraction schema. The
application supplies reviewed asset locations instead of asking an LLM to invent coordinates.
Validated closures are cached so routing continues when the data source or AI service fails.

Current evidence: a real cached graph with 6,885 nodes and 15,618 edges; an offline three-route
comparison; a tested parsing-to-rerouting flow; an authenticated live SharePoint scrape of
1,095 distinct notices with unresolved locations retained for review; and live PVTA/RSS
discovery with separately labeled review candidates. Reddit/Facebook adapters need authorized
API credentials before they can fetch data.

## 90-second rehearsal

1. **0–15 seconds:** explain a concrete trip disrupted by an elevator outage.
2. **15–35 seconds:** compare the synthetic shortest route with the synthetic step-free route.
   Label the controlled fixture clearly; show 111 m versus 177 m.
3. **35–55 seconds:** insert the synthetic elevator closure and show the 243 m detour. Explain
   that graph search runs locally and does not wait for AI.
4. **55–75 seconds:** show one notice handled by rules, then an ambiguous notice sent to the
   optional Gemini fallback. Use an actual live success only after it has been verified.
5. **75–90 seconds:** show source-observation freshness and the unresolved-location queue.
   Explain the path to precise asset mapping and real-time community reports.

## Before making broader claims

- Real elevator/entrance mappings remain missing; the OSM graph currently has no elevator edges.
- Live Gemini access is implemented but not yet verified in this environment.
- The live SharePoint connector works with a saved operator session. Unattended deployment
  needs approved service authentication; students do not authenticate to the source themselves.
- MongoDB Atlas and community-report merging belong to Role 4 and are not implemented here.
- The polished map, report button, video recording, and submission belong to the team and
  have not been completed by these backend changes.
- Terrain grades are estimates; do not describe the app as ADA-certified or field verified.

Suggested submission topics: accessibility, campus navigation, geospatial routing, and Gemini
structured extraction. Confirm current event categories and sponsor eligibility with the
organizers before selecting tracks. This document is a draft; no submission has been made.
