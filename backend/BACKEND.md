# CampusNav

## Backend API

From the repo root in PowerShell with Python 3.11 or later:

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open [interactive API docs](http://127.0.0.1:8000/docs). The default local server stores reports in memory until it restarts. Set `$env:CAMPUSNAV_DEMO = '1'` before starting it to load one sample ramp closure from `backend/closures.json`.

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | Process liveness |
| GET | `/closures` | Active closures, most recently confirmed first |
| POST | `/reports` | Created closure with HTTP 201 |
| POST | `/reports/{report_id}/confirm` | Active community closure with a renewed expiry, or HTTP 404 |

Submit a report from a second PowerShell window:

```powershell
$report = @{
    lat = 42.3912
    lng = -72.5267
    type = 'elevator'
    radius = 10
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/reports -ContentType application/json -Body $report
Invoke-RestMethod -Uri http://127.0.0.1:8000/closures
```

`lat` and `lng` are decimal degrees. `type` accepts `elevator`, `ramp`, `path`, or `construction`. `radius` is in meters and defaults to 10. Community reports expire exactly 48 hours after submission or their most recent confirmation. The backend sets `end_time`. Send a POST with no body to `/reports/{report_id}/confirm` using the report's `id`. Confirmation applies to active community reports. The endpoint is anonymous and does not verify whether the confirmer is a different user.

Set `CORS_ORIGINS` to a comma-separated list of frontend origins if your frontend runs somewhere other than `http://localhost:5173` or `http://127.0.0.1:5173`.

## MongoDB Atlas

Set `MONGODB_URI` in `backend/.env` and keep the file local. `MONGODB_DB` defaults to `campusnav`. From the repo root, start the API with:

```cmd
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --env-file backend\.env
```

The Atlas database user needs read/write access to `campusnav`. The backend initializes the `closures` collection and its expiration index on startup. Each successful `POST /reports` creates one document in that collection.

| Stored fields | BSON type | Meaning |
| --- | --- | --- |
| `_id` | String | UUID returned by the API as `id` |
| `lat`, `lng` | Double | Coordinates in decimal degrees |
| `radius` | Double | Affected area radius in meters |
| `type` | String | `elevator`, `ramp`, `path`, or `construction` |
| `status`, `source` | String | New reports use `closed` and `community` |
| `start_time`, `end_time`, `last_confirmed` | Date | UTC activation, expiration, and last confirmation timestamps |

MongoDB uses a unique index on `_id` and a TTL index on `end_time` to delete expired reports. The API filters out expired reports as soon as their end time passes.
On startup, the backend updates still-active older community reports to expire 48 hours after their last confirmation. Reports that have already expired stay expired.

After `POST /reports` returns HTTP 201, open **Data Explorer → campusnav → closures → Documents** in Atlas and look for the document with the returned `id` as its `_id`.

### Official maintenance notices

Role 3 owns retrieval from the UMass [Current Interruptions SharePoint view](https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx?viewid=49a9fec0-8dcc-47f9-a618-92f4c4aba861). The MongoDB backend reads a document in `official_snapshots` with `_id: "umass-service-interruptions"` and a `closures` array. Each entry follows the API closure schema with a string `id`, `source: "official"`, `end_time: null`, and BSON dates for `start_time` and `last_confirmed`.

Replace the array after successfully retrieving the complete current view. `GET /closures` serves entries once their start time has arrived. Official notices have no TTL and disappear from the API when omitted from the next successful refresh.
