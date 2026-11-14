# CampusNav Backend

## Start the API

From the repo root in PowerShell with Python 3.11 or later, create the virtual environment and install the dependencies once:

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

For local testing, start the API in memory mode. Data is cleared when the server restarts.

```powershell
$env:CAMPUSNAV_ADMIN_KEY = 'local-test-key'
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Open [Swagger UI](http://127.0.0.1:8000/docs). Expand an endpoint, click **Try it out**, and click **Execute**. For a POST request, paste the JSON example into the request body first.

Building and official report writes require an `X-Admin-Key` header. In Swagger, click **Authorize** and enter the configured key. The key above is for local testing. Use a separate secret for shared deployments and keep it out of frontend code.

## Which endpoint should I use?

| Endpoint | Returns |
| --- | --- |
| `GET /buildings` | Building locations, entrances, automatic doors, and elevator counts |
| `GET /official-reports` | The latest official notices, including scheduled closures |
| `GET /community-reports` | Active community reports |
| `GET /external-reports` | Unexpired scraped public reports awaiting review |
| `GET /closures` | The combined feed of active official and community closures for routing |
| `GET /health` | `{"status":"ok"}` when the API is responding |

Fetch **`GET /buildings`** for building and entrance data and **`GET /closures`** for current routing obstructions. The closure feed is sorted by newest `last_confirmed` first. If both sources report the same obstruction, both entries can appear. Each entry has a `source` field. List endpoints return `[]` when there are no matching records.

## Buildings

**`POST /buildings`** creates one building and returns HTTP 201. Use a unique lowercase ID such as `example-building`. A duplicate ID returns HTTP 409. Use verified coordinates and accessibility attributes when adding real buildings.

```json
{
  "id": "example-building",
  "name": "Example Building",
  "lat": 42.3912,
  "lng": -72.5267,
  "elevators": [
    { "location": "Ground floor, across from the main entrance" }
  ],
  "bathrooms": [
    { "location": "Ground floor, room 102", "transfer_type": "left" }
  ],
  "entrances": [
    {
      "name": "Main entrance",
      "lat": 42.3911,
      "lng": -72.5267,
      "step_free": true,
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
        "name": "Main entrance",
        "step_free": true,
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
        "lat": null,
        "lng": null
      }
    ],
    "bathrooms": [
      {
        "location": "Ground floor, room 102",
        "lat": null,
        "lng": null,
        "transfer_type": "left"
      }
    ]
  }
]
```

Use a room, floor, or landmark for an indoor `location`. Add `lat` and `lng` when available. Use `null` for an unknown bathroom transfer type or entrance flag. If you omit `elevator_count`, the API counts the listed elevators. Use `null` if the physical elevator count is unknown. The API also accepts the older `automatic_door` field.

## Official reports

**`POST /official-reports`** replaces the manually managed official list and returns it with HTTP 200. An empty `closures` array clears that list. The scraper importer updates its own entries within the same collection. **`GET /official-reports`** includes both. [UMass Current Interruptions](https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx?viewid=49a9fec0-8dcc-47f9-a618-92f4c4aba861)

```json
{
  "closures": [
    {
      "id": "umass-123",
      "description": "Example elevator interruption near the main entrance",
      "type": "elevator",
      "location": { "lat": 42.3912, "lng": -72.5267 },
      "start_time": "2026-11-14T14:00:00Z",
      "end_time": "2026-11-14T18:00:00Z"
    }
  ]
}
```

Use a stable ID for each notice and ISO 8601 timestamps with a timezone. The start time defaults to when the list is posted. Use `null` for an open-ended notice. The routing feed shows a notice from its start until its end or until a refresh omits it. Official reports are retained in the snapshot until the next replacement. They have no TTL.

**`GET /official-reports`** lists the saved notices, including future ones. [Try the GET request](http://127.0.0.1:8000/official-reports).

```json
[
  {
    "lat": 42.3912,
    "lng": -72.5267,
    "radius": 10.0,
    "type": "elevator",
    "id": "umass-123",
    "status": "closed",
    "source": "official",
    "start_time": "2026-11-14T14:00:00Z",
    "end_time": "2026-11-14T18:00:00Z",
    "last_confirmed": "2026-11-14T15:00:00Z",
    "title": "Example elevator interruption near the main entrance",
    "details": null,
    "description": "Example elevator interruption near the main entrance",
    "last_updated": "2026-11-14T15:00:00Z",
    "location": {
      "lat": 42.3912,
      "lng": -72.5267
    }
  }
]
```

## Community reports

**`POST /community-reports`** creates one report and returns HTTP 201. Use `elevator`, `ramp`, `path`, or `construction` for `type`. Coordinates are in decimal degrees. The optional `radius` defaults to 10 meters and also applies to official reports.

```json
{
  "lat": 42.3912,
  "lng": -72.5267,
  "type": "ramp",
  "radius": 10
}
```

**`GET /community-reports`** lists reports that are still active. [Try the GET request](http://127.0.0.1:8000/community-reports).

```json
[
  {
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
    "title": null,
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

**`GET /closures`** combines active official and community reports. In memory demo mode, the sample ramp can also appear with `source: "demo"`. [Try the GET request](http://127.0.0.1:8000/closures).

```json
[
  {
    "lat": 42.3912,
    "lng": -72.5267,
    "radius": 10.0,
    "type": "elevator",
    "id": "umass-123",
    "status": "closed",
    "source": "official",
    "start_time": "2026-11-14T14:00:00Z",
    "end_time": "2026-11-14T18:00:00Z",
    "last_confirmed": "2026-11-14T15:00:00Z",
    "title": "Example elevator interruption near the main entrance",
    "details": null,
    "description": "Example elevator interruption near the main entrance",
    "last_updated": "2026-11-14T15:00:00Z",
    "location": {
      "lat": 42.3912,
      "lng": -72.5267
    }
  },
  {
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
    "title": null,
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

## Health

**`GET /health`** returns the API liveness status. [Try the GET request](http://127.0.0.1:8000/health).

```json
{
  "status": "ok"
}
```

## Use MongoDB Atlas

Set `MONGODB_URI` in `backend/.env` to the Atlas connection string. The database name defaults to `campusnav` and can be set with `MONGODB_DB`. Set `CAMPUSNAV_ADMIN_KEY` in the same file to enable protected writes. Keep the file local.

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --env-file backend\.env
```

The Atlas database user needs read/write access. The backend uses these collections:

| Collection | Storage |
| --- | --- |
| `Buildings` | One document per building, keyed by the building ID |
| `OfficialClosures` | The manually managed official list and one capture per official scraper source |
| `CommunityReports` | One document per user report with a TTL index on `end_time`, and one review capture per public scraper source |

In Atlas Data Explorer, a community report's MongoDB `_id` matches the API response's `id`. The API hides a report when it expires, and MongoDB removes it during TTL cleanup.

### Import scraped data

Start the Data API with the Atlas settings above:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --env-file backend\.env --port 8001
```

From another terminal at the repository root, use the Python environment you set up for the
combined scraper:

```powershell
.\refresh-scrapers.cmd --rules-only
.\.venv\Scripts\python.exe -m scripts.post_scraped_data
.\.venv\Scripts\python.exe -m scripts.post_scraped_data --apply
```

The first upload command previews the destination and record counts. `--apply` sends the
processed data using `CAMPUSNAV_ADMIN_KEY` from the environment or `backend/.env`. Pass
`--api-url` to target a different Data API, or use `--only buildings`, `--only official`, or
`--only public` to sync one kind of data.

| Input | Destination | Read back from |
| --- | --- | --- |
| Saved ArcGIS building catalog | `Buildings` by building ID. Existing IDs retain their records. | `/buildings` |
| Resolved SharePoint notices | `OfficialClosures` in a document such as `official:umass-maintenance`. | `/official-reports`, or `/closures` for current closures |
| Public reports from PVTA, Reddit, Collegian, or Facebook | `CommunityReports` in a document such as `public:umass-reddit`. Each item keeps its source, review flag, and expiry. | `/external-reports` |

Each successful scrape replaces its own capture. An empty success clears that source's records.
A failed refresh leaves the previous records available. The importer skips older and duplicate
captures. An unverified public report is available for review until expiry and has no effect on
routing. If your database has MongoDB validators for the earlier record shapes, extend the
installed rules before uploading:

```powershell
.\backend\.venv\Scripts\python.exe -m backend.mongo_schema --scraper-imports
.\backend\.venv\Scripts\python.exe -m backend.mongo_schema --scraper-imports --apply
```

### MongoDB schema validation

MongoDB validators check coordinates and building accessibility fields, official notice snapshots, and the community report dates used for TTL. Official `end_time` accepts a BSON Date or `null`. The validators accept older records that predate the new fields.

From the repo root, check the configured database or install the validators:

```powershell
.\backend\.venv\Scripts\python.exe -m backend.mongo_schema
.\backend\.venv\Scripts\python.exe -m backend.mongo_schema --apply
```

Both commands check existing documents first. Installing the validators requires MongoDB's `collMod` permission. The API's normal startup does not need this permission.

## Local options

- Set `CAMPUSNAV_DEMO=1` before starting in memory mode to load the sample ramp closure from `backend/closures.json`.
- Set `CORS_ORIGINS` to a comma-separated list of frontend origins. The defaults are `http://localhost:5173` and `http://127.0.0.1:5173`.
