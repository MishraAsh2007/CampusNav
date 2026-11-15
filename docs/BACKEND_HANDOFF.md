# Role 4 integration review for Roles 1 and 3

Reviewed November 14, 2026 against the shared
[BACKEND.md](https://github.com/MishraAsh2007/CampusNav/blob/main/backend/BACKEND.md),
[main.py](https://github.com/MishraAsh2007/CampusNav/blob/main/backend/main.py) and
[MongoDB validators](https://github.com/MishraAsh2007/CampusNav/blob/main/backend/mongo_schema.py).
Files on `main` can change after this review. The inspected `main.py` blob was
`21c75b622b0d7cace0c2d4e1d0abeec96f99abaf`.

**The basic outdoor data service is present. We do not yet have a complete compatible
indoor integration.** Most work is additive contract alignment, not a replacement backend.
No Role 4 files or database records were changed for this review.

## What is already there

- `GET /buildings`: building coordinates, entrances, door/access flags and elevator descriptions.
- `GET /closures`: active official and community records with coordinates, radius and times.
- `POST /official-reports`: protected atomic replacement of the official list.
- Community report creation, confirmation, expiry filtering and MongoDB TTL storage.
- Optional Atlas storage, with in-memory mode for local development.

An ordinary `elevator`, `ramp` or `path` closure with `source: official/community` and
`status: closed` matches our routing fields. Extra descriptive metadata is tolerated by
our Closure model. Full compatibility still requires the changes below.

## Required handoff changes

| Priority / owner | Request | Reason |
| --- | --- | --- |
| Indoor blocker — Role 4 | Preserve optional `building_id`, `asset_id`, `floor_id` on official/community write inputs, stored records and `/closures` responses | Latitude/longitude cannot distinguish floors or nearby elevator shafts. Our indoor router needs exact reviewed scope. Require `building_id` when `floor_id` is supplied. |
| Indoor identity — shared IDs, stored by Role 4 where applicable | Stable IDs for entrances and elevator assets; use the same building IDs as the graph (`library`, `ilc`) | A text description such as “near entrance” is insufficient to join a report to a particular graph connection. IDs must survive edits and be mapped explicitly from any existing IDs. |
| Source fidelity — Role 4 | Accept/preserve `last_confirmed` from Role 3 and retain `source_ref`/URL, `source_id`, `confirmation_kind`, plus snapshot observation/fallback status | The current official endpoint sets every `last_confirmed` to upload time. Re-uploading an old cache would make stale source data appear newly confirmed. Keep ingestion time separate. |
| Status contract — Role 4 | Support `closed` and `degraded` for official closures | Our parser can publish degraded access and the router penalizes it. The current service forces `closed`, changing the meaning. Working/restoration observations must remove/resolve the matching active issue, not become a `working` route obstruction. |
| Compatibility adapter — Roles 1/3 | Convert `construction` to route type `path`; keep demo records separate; validate radius `0 < radius <= 1000` | Our router accepts `elevator/ramp/path` and `official/community/verified`. Role 4 additionally permits `construction` and `demo`. Passing those unchanged returns HTTP 422. Do not relabel demo data as real evidence. |
| Operational wiring — Roles 1/3 with Role 4 | Agree on the reachable data-API URL and provision the admin key privately for the worker | The local guided API currently reads local snapshots. Adding Atlas fields does not automatically connect the two services. Keep the key out of client code and documentation. |

The relevant Role 4 models are `OfficialNotice`, `ReportCreate`, `Closure`, `IndoorLocation`
and `Entrance`, plus their MongoDB validators. Several write models use `extra="forbid"`,
so adding these fields only to our JSON will produce HTTP 422. The Closure response model
also lacks the indoor IDs; simply putting them into MongoDB will not expose them reliably.

The complete schema our router accepts is [closure.schema.json](../contracts/closure.schema.json).
Optional indoor scope should retain support for existing outdoor-only records. An
unscoped elevator closure must not be guessed onto every floor.

### Proposed scoped closure

This is a **contract example**, not an actual ILC outage or an established elevator ID.
The asset ID must be replaced by one assigned during map review.

```json
{
  "id": "example-notice-123",
  "lat": 42.3912,
  "lng": -72.5267,
  "radius": 10,
  "type": "elevator",
  "status": "closed",
  "source": "official",
  "building_id": "ilc",
  "asset_id": "example-ilc-elevator-a",
  "floor_id": null,
  "start_time": "2026-11-14T14:00:00Z",
  "end_time": "2026-11-14T18:00:00Z",
  "last_confirmed": "2026-11-14T13:45:00Z"
}
```

For a whole-shaft outage, omit/null `floor_id` and identify the elevator asset. A particular
landing or floor-scoped incident needs its documented `floor_id`. Do not attach the user's
current floor to a whole-elevator outage merely because that is where the report was made.

## Decisions to align before integration

1. **Expiry:** Role 4 currently uses 48 hours; the original project brief and our local
   community implementation use 24 hours. Routing can obey either expiry timestamp, but
   the team should choose one rule and make the documentation/interface agree.
2. **Precedence and restoration:** the shared `/closures` combines both lists and can return
   duplicates. It does not implement the brief's 12-hour override rule or a working/resolve
   endpoint. Duplicates alone are not the main routing blocker, but resolving one exact
   asset and preserving active official closures require an agreed policy.
3. **Unknown entrance access:** their `step_free` is a required Boolean, while some of our
   real entrance records have unknown access. Permit `null` or keep an explicit unknown
   state; do not coerce unknown into verified `true`. Their existing nullable opener and
   keycard flags should remain nullable too.
4. **Building shape:** Role 4's `/buildings` is a list; our local `/buildings` response is a
   catalog object and includes routing-specific metadata. Fields such as `door_type`,
   `keycard_required`, `in_routing_area` and entrance IDs also differ. Use an explicit
   adapter/ID mapping before substituting the URL in the current integration.

## What remains our responsibility

Role 1 owns reviewed indoor graphs, room/landing IDs, paths, entrance-to-outdoor connections,
location clarification and the `/navigation/*` routing flow. Role 3 owns scraping, source
evidence, floor/room references, notice parsing and preparing complete snapshots.

Role 4 does **not** need to implement pathfinding, trace floor plans, run Gemini in a route
request or own the conversation state. For the hackathon the reviewed graph can remain
in our versioned JSON files. Atlas storage for indoor maps is optional; it is not required
to make the current routing engine work. If Role 4 adds `floors_served` to its elevator
catalog, those values must come from documented stops and match our IDs; a list alone does
not replace a walkable graph.

The real indoor data gap remains even after schema changes: ILC/library corridors, doorways,
actual stops and entrance connections still need tracing/review. See
[INDOOR_SOURCE_AUDIT.md](INDOOR_SOURCE_AUDIT.md).

## Connection plan and acceptance checks

1. Role 4 extends its request models, response models and Mongo validators together.
2. Role 3 adds a publication adapter to `POST /official-reports` using `X-Admin-Key`.
   The existing scraper's `PublishedClosure` has additional fields and cannot be posted
   unchanged. Publish the complete validated snapshot, including future notices. A failed
   or partial scrape must retain the previous list; never send an empty array on failure.
   A successfully verified empty result is distinct and can legitimately clear the list.
3. Role 1 or the calling client obtains `/closures`, validates/translates the agreed contract,
   and supplies it to routing. Fetch it again at arrival; do not rely on the departure copy.
   Our guided endpoint's current omitted-closures default uses the **local** snapshot,
   not Role 4's remote URL. A remote-provider adapter is still needed for that default.
4. Verify an exact asset outage chooses another reviewed elevator; a floor-scoped incident
   does not close unrelated floors; stale source data remains stale after upload; scheduled
   notices do not block early; restoration and expiry follow the team's chosen policy.

Run the two services on distinct ports or behind explicit proxy routes. Both setup guides
currently default to port 8000, so they cannot both bind that address unchanged. No live
Role 4 server, Atlas connection or admin key was used during this review.
