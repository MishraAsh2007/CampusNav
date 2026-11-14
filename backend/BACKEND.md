# CampusNav Backend

## Start the API

From the repo root in PowerShell with Python 3.11 or later, create the virtual environment and install the dependencies once:

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

For local testing, start the API in memory mode. Data is cleared when the server restarts.

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Open [Swagger UI](http://127.0.0.1:8000/docs). Expand an endpoint, click **Try it out**, and click **Execute**. For a POST request, paste the JSON example into the request body first.

The write endpoints accept requests without an admin key.

## Which endpoint should I use?

| Endpoint | Returns |
| --- | --- |
| `GET /buildings` | Building locations, entrances, automatic doors, and elevator counts |
| `GET /official-reports` | The latest official notices, including scheduled closures |
| `GET /community-reports` | Active community reports |
| `GET /closures` | The combined feed of active official and community closures for routing |
| `GET /health` | `{"status":"ok"}` when the API is responding |

Fetch **`GET /buildings`** for building and entrance data and **`GET /closures`** for current routing obstructions. The closure feed is sorted by newest `last_confirmed` first, with unknown confirmation times last. If both sources report the same obstruction, both entries can appear. Each entry has a `source` field. List endpoints return `[]` when there are no matching records.

## Buildings

**`POST /buildings`** creates one building and returns HTTP 201. A duplicate ID returns HTTP 409. Use the exact building ID from the routing catalog, such as `ilc`. IDs can contain lowercase letters, numbers, hyphens, and underscores.

**`PUT /buildings/{building_id}`** creates or replaces the entire building record and returns HTTP 200. Send the same payload as for POST and match the body `id` to the URL. For edits and re-imports, reuse the catalog IDs even if names, coordinates, or array order change. Each entrance needs its routing doorway `id`, and each elevator needs its routing shaft `asset_id`. Entrance IDs and elevator asset IDs must each be unique within the building. Use that same `asset_id` in closure reports for the elevator.

```json
{
  "id": "example-building",
  "name": "Example Building",
  "lat": 42.3912,
  "lng": -72.5267,
  "elevators": [
    {
      "location": "Ground floor, across from the main entrance",
      "building_id": "example-building",
      "asset_id": "example-building-elevator-a",
      "floor_id": "1"
    }
  ],
  "bathrooms": [
    { "location": "Ground floor, room 102", "transfer_type": "left" }
  ],
  "entrances": [
    {
      "id": "example-building-main",
      "name": "Main entrance",
      "lat": 42.3911,
      "lng": -72.5267,
      "step_free": null,
      "hasAutoDoorOpener": true,
      "isAccessibleToAllFloors": true,
      "IsKeyCardRequired": false
    }
  ]
}
```

**`GET /buildings`** lists the saved buildings. [Try the GET request](http://127.0.0.1:8000/buildings).

```json
[
  {
    "lat": 42.3912,
    "lng": -72.5267,
    "id": "example-building",
    "name": "Example Building",
    "entrances": [
      {
        "lat": 42.3911,
        "lng": -72.5267,
        "id": "example-building-main",
        "name": "Main entrance",
        "step_free": null,
        "hasAutoDoorOpener": true,
        "isAccessibleToAllFloors": true,
        "IsKeyCardRequired": false,
        "automatic_door": true
      }
    ],
    "elevator_count": 1,
    "elevators": [
      {
        "location": "Ground floor, across from the main entrance",
        "building_id": "example-building",
        "asset_id": "example-building-elevator-a",
        "floor_id": "1",
        "lat": null,
        "lng": null
      }
    ],
    "bathrooms": [
      {
        "location": "Ground floor, room 102",
        "building_id": null,
        "asset_id": null,
        "floor_id": null,
        "lat": null,
        "lng": null,
        "transfer_type": "left"
      }
    ]
  }
]
```

Use a room, floor, or landmark for an indoor `location`. Add `lat` and `lng` when available. Use `null` for an unknown bathroom transfer type or entrance flag. The API counts the listed elevators unless you supply `elevator_count` for a building with only some elevator locations recorded. It also accepts the older `automatic_door` field.

Set `step_free` to `null` when doorway accessibility is unverified. Older saved buildings can still be read. Their entrance and elevator IDs may be `null` until the building is re-imported with catalog IDs. The example IDs above are for testing. Use the IDs from the graph version your app routes against. In the map branch's current catalog, Campus Center uses `campus-center` and its west doorway uses `cc-west`. Its concourse elevator uses `cc-concourse-elevator` in the graph.

## Official reports

**`POST /official-reports`** replaces the full official list and returns it with HTTP 200. Use the sample below on a local test server. In the live integration, Role 3 should send the complete list after a successful retrieval from UMass SharePoint. An empty `closures` array clears the list. [UMass Current Interruptions](https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx?viewid=49a9fec0-8dcc-47f9-a618-92f4c4aba861)

```json
{
  "snapshot_observed_at": "2026-11-14T13:45:00Z",
  "snapshot_fallback": true,
  "closures": [
    {
      "id": "umass-123",
      "description": "Construction narrows the walkway near the main entrance",
      "type": "construction",
      "status": "degraded",
      "location": { "lat": 42.3912, "lng": -72.5267 },
      "building_id": "ilc",
      "asset_id": "example-ilc-main-walkway",
      "floor_id": null,
      "published_at": "2026-11-14T13:00:00Z",
      "last_confirmed": "2026-11-14T13:40:00Z",
      "source_ref": "https://example.org/notices/123",
      "source_id": "123",
      "confirmation_kind": "source_observation",
      "start_time": "2026-11-14T14:00:00Z",
      "end_time": "2026-11-14T18:00:00Z"
    }
  ]
}
```

Use a stable ID for each notice and ISO 8601 timestamps with a timezone. The start time defaults to when the list is posted. Use `null` for an open-ended notice. The routing feed shows a notice from its start until its end or until a refresh omits it. Official reports are retained in the snapshot until the next replacement. They have no TTL.

Use `status: "closed"` for a full obstruction or `status: "degraded"` when a route remains usable with reduced accessibility. Omitting `status` defaults to `closed`. `GET /closures` returns the supplied status so the router can penalize degraded paths while keeping them available.

When the source reports that service is restored, omit the resolved notice from the next complete official snapshot. If the notice has a known end time, it leaves the active routing feed at `end_time`. A payload with `status: "working"` returns HTTP 422 and leaves the current snapshot intact.

`last_confirmed` is the source's confirmation time. Omit it or send `null` when unknown. The API records the upload separately as `ingested_at`, and `last_updated` mirrors `last_confirmed`. Re-uploading a cached notice leaves its confirmation time intact.

`published_at` is the source's publication time when available. `source_ref` holds the source URL or reference, `source_id` holds the source's own record ID, and `confirmation_kind` describes how the record was confirmed. Set `snapshot_observed_at` to when the snapshot was originally observed and `snapshot_fallback` to `true` when uploading a fallback snapshot. These two fields can be supplied once for the snapshot or on individual notices. Per-notice values take precedence.

**`GET /official-reports`** lists the saved notices, including future ones. [Try the GET request](http://127.0.0.1:8000/official-reports).

```json
[
  {
    "snapshot_observed_at": "2026-11-14T13:45:00Z",
    "snapshot_fallback": true,
    "source_ref": "https://example.org/notices/123",
    "source_id": "123",
    "confirmation_kind": "source_observation",
    "published_at": "2026-11-14T13:00:00Z",
    "building_id": "ilc",
    "asset_id": "example-ilc-main-walkway",
    "floor_id": null,
    "lat": 42.3912,
    "lng": -72.5267,
    "radius": 10.0,
    "type": "construction",
    "id": "umass-123",
    "status": "degraded",
    "source": "official",
    "start_time": "2026-11-14T14:00:00Z",
    "end_time": "2026-11-14T18:00:00Z",
    "last_confirmed": "2026-11-14T13:40:00Z",
    "ingested_at": "2026-11-14T15:00:00Z",
    "title": "Construction narrows the walkway near the main entrance",
    "details": null,
    "description": "Construction narrows the walkway near the main entrance",
    "last_updated": "2026-11-14T13:40:00Z",
    "location": {
      "lat": 42.3912,
      "lng": -72.5267
    }
  }
]
```

## Community reports

**`POST /community-reports`** creates one report and returns HTTP 201. Use `elevator`, `ramp`, `path`, or `construction` for `type`. Coordinates are in decimal degrees. The optional `radius` defaults to 10 meters and also applies to official reports.

Pass an optional `title` to name the report. The API trims surrounding whitespace and rejects a blank title with HTTP 422. Omit the title or send `null` for an untitled report. The saved title appears in the POST response, `GET /community-reports`, and `GET /closures`.

```json
{
  "lat": 42.3912,
  "lng": -72.5267,
  "type": "ramp",
  "title": "Ramp blocked near the main entrance",
  "radius": 10
}
```

**`GET /community-reports`** lists reports that are still active. [Try the GET request](http://127.0.0.1:8000/community-reports).

```json
[
  {
    "snapshot_observed_at": null,
    "snapshot_fallback": null,
    "source_ref": null,
    "source_id": null,
    "confirmation_kind": null,
    "published_at": null,
    "building_id": null,
    "asset_id": null,
    "floor_id": null,
    "lat": 42.3912,
    "lng": -72.5267,
    "radius": 10.0,
    "type": "ramp",
    "id": "2bcb2b35-865c-4b1e-b7cb-f4a4360016c3",
    "status": "closed",
    "source": "community",
    "start_time": "2026-11-14T15:00:00Z",
    "end_time": "2026-11-16T15:00:00Z",
    "last_confirmed": "2026-11-14T15:00:00Z",
    "ingested_at": null,
    "title": "Ramp blocked near the main entrance",
    "details": null,
    "description": null,
    "last_updated": "2026-11-14T15:00:00Z",
    "location": {
      "lat": 42.3912,
      "lng": -72.5267
    }
  }
]
```

The server generates `id`, `start_time`, `end_time`, `source` (always `community`), and `last_updated`. Each submission creates a new report that expires after 48 hours. To renew an existing one, copy its `id` and call **`POST /community-reports/{report_id}/confirm`** with an empty body. Confirmation updates `last_updated` and extends expiry by 48 hours from the confirmation time. `last_confirmed` is still available for existing clients. A missing or expired report returns HTTP 404.

## Combined closures

Official and community reports can include `building_id`, `asset_id`, and `floor_id`. These fields are optional strings. A non-null `floor_id` requires `building_id`, and `floor_id: null` can represent an outage affecting a whole elevator shaft. The same fields are accepted on indoor elevator and bathroom locations under `POST /buildings`. `GET /closures` returns these references, with omitted values shown as `null`.

**`GET /closures`** combines active official and community reports. In memory demo mode, the sample ramp can also appear with `source: "demo"`. [Try the GET request](http://127.0.0.1:8000/closures).

```json
[
  {
    "snapshot_observed_at": null,
    "snapshot_fallback": null,
    "source_ref": null,
    "source_id": null,
    "confirmation_kind": null,
    "published_at": null,
    "building_id": null,
    "asset_id": null,
    "floor_id": null,
    "lat": 42.3912,
    "lng": -72.5267,
    "radius": 10.0,
    "type": "ramp",
    "id": "2bcb2b35-865c-4b1e-b7cb-f4a4360016c3",
    "status": "closed",
    "source": "community",
    "start_time": "2026-11-14T15:00:00Z",
    "end_time": "2026-11-16T15:00:00Z",
    "last_confirmed": "2026-11-14T15:00:00Z",
    "ingested_at": null,
    "title": "Ramp blocked near the main entrance",
    "details": null,
    "description": null,
    "last_updated": "2026-11-14T15:00:00Z",
    "location": {
      "lat": 42.3912,
      "lng": -72.5267
    }
  },
  {
    "snapshot_observed_at": "2026-11-14T13:45:00Z",
    "snapshot_fallback": true,
    "source_ref": "https://example.org/notices/123",
    "source_id": "123",
    "confirmation_kind": "source_observation",
    "published_at": "2026-11-14T13:00:00Z",
    "building_id": "ilc",
    "asset_id": "example-ilc-main-walkway",
    "floor_id": null,
    "lat": 42.3912,
    "lng": -72.5267,
    "radius": 10.0,
    "type": "construction",
    "id": "umass-123",
    "status": "degraded",
    "source": "official",
    "start_time": "2026-11-14T14:00:00Z",
    "end_time": "2026-11-14T18:00:00Z",
    "last_confirmed": "2026-11-14T13:40:00Z",
    "ingested_at": "2026-11-14T15:00:00Z",
    "title": "Construction narrows the walkway near the main entrance",
    "details": null,
    "description": "Construction narrows the walkway near the main entrance",
    "last_updated": "2026-11-14T13:40:00Z",
    "location": {
      "lat": 42.3912,
      "lng": -72.5267
    }
  }
]
```

## Health

**`GET /health`** returns the API liveness status. [Try the GET request](http://127.0.0.1:8000/health).

```json
{
  "status": "ok"
}
```

## Use MongoDB Atlas

Set `MONGODB_URI` in `backend/.env` to the Atlas connection string. The database name defaults to `campusnav` and can be set with `MONGODB_DB`. Keep the file local.

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --env-file backend\.env
```

The Atlas database user needs read/write access. The backend initializes these collections on startup:

| Collection | Storage |
| --- | --- |
| `Buildings` | One document per building, keyed by the building ID |
| `OfficialClosures` | One document with `_id` set to `umass-service-interruptions` and a `closures` array |
| `CommunityReports` | One document per report, with dates stored in UTC and a TTL index on `end_time` |

In Atlas Data Explorer, a community report's MongoDB `_id` matches the API response's `id`. The API hides a report when it expires, and MongoDB removes it during TTL cleanup.

### MongoDB schema validation

MongoDB validators check coordinates and building accessibility fields, official notice snapshots, and the community report dates used for TTL. Official `end_time` accepts a BSON Date or `null`. The validators accept older records that predate the new fields.

From the repo root, check the configured database or install the validators:

```powershell
.\backend\.venv\Scripts\python.exe -m backend.mongo_schema
.\backend\.venv\Scripts\python.exe -m backend.mongo_schema --apply
```

Both commands check existing documents first. Applying the schema also creates compound indexes for looking up community and official closures by building, asset, and floor. For official closures, use `$elemMatch` on the `closures` array to match those fields on the same notice. Applying requires MongoDB's `collMod` and `createIndex` permissions.

## Local options

- Set `CAMPUSNAV_DEMO=1` before starting in memory mode to load the sample ramp closure from `backend/closures.json`.
- Set `CORS_ORIGINS` to a comma-separated list of frontend origins. The defaults are `http://localhost:5173` and `http://127.0.0.1:5173`.
