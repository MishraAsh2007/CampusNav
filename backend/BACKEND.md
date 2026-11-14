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
| `GET /closures` | The combined feed of active official and community closures for routing |
| `GET /health` | `{"status":"ok"}` when the API is responding |

Fetch **`GET /buildings`** for building and entrance data and **`GET /closures`** for current routing obstructions. The closure feed is sorted by newest `last_confirmed` first. If both sources report the same obstruction, both entries can appear. Each entry has a `source` field.

## Buildings

**`POST /buildings`** creates one building and returns HTTP 201. Use a unique lowercase ID such as `example-building`. A duplicate ID returns HTTP 409. Use verified coordinates and accessibility attributes when adding real buildings.

```json
{
  "id": "example-building",
  "name": "Example Building",
  "lat": 42.3912,
  "lng": -72.5267,
  "elevator_count": 1,
  "entrances": [
    {
      "name": "Main entrance",
      "lat": 42.3911,
      "lng": -72.5267,
      "step_free": true,
      "automatic_door": true
    }
  ]
}
```

**`GET /buildings`** lists the saved buildings. [Try the GET request](http://127.0.0.1:8000/buildings).

## Official reports

**`POST /official-reports`** replaces the full official list and returns it with HTTP 200. Use the sample below on a local test server. In the live integration, Role 3 should send the complete list after a successful retrieval from UMass SharePoint. An empty `closures` array clears the list. [UMass Current Interruptions](https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx?viewid=49a9fec0-8dcc-47f9-a618-92f4c4aba861)

```json
{
  "closures": [
    {
      "id": "umass-123",
      "title": "Example elevator interruption",
      "type": "elevator",
      "lat": 42.3912,
      "lng": -72.5267
    }
  ]
}
```

Use a stable ID for each notice. You can include `details` and an ISO 8601 `start_time` with a timezone. The start time defaults to when the list is posted. A notice enters the routing feed when its start time arrives and stays there until a refresh omits it.

**`GET /official-reports`** lists the saved notices, including future ones. [Try the GET request](http://127.0.0.1:8000/official-reports).

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

The API generates the report `id`, sets `last_confirmed`, and sets expiry 48 hours ahead. Each submission creates a new report. To renew an existing one, copy its `id` and call **`POST /community-reports/{report_id}/confirm`** with an empty body. Confirmation is anonymous and extends expiry to 48 hours from the confirmation. A missing or expired report returns HTTP 404.

## Use MongoDB Atlas

Set `MONGODB_URI` in `backend/.env` to the Atlas connection string. The database name defaults to `campusnav` and can be set with `MONGODB_DB`. Set `CAMPUSNAV_ADMIN_KEY` in the same file to enable protected writes. Keep the file local.

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

## Local options

- Set `CAMPUSNAV_DEMO=1` before starting in memory mode to load the sample ramp closure from `backend/closures.json`.
- Set `CORS_ORIGINS` to a comma-separated list of frontend origins. The defaults are `http://localhost:5173` and `http://127.0.0.1:5173`.
