# Official data: UMass Service Interruption Notices

Turns the login-only SharePoint export of Service Interruption Notices (SINs) into
`elevator_out` closures for the routing engine.

## Files

| Path | In git | What |
|---|---|---|
| `data/raw/Service_Interruption_Notices.csv` | no | Manual export from the SharePoint list (requires UMass login) |
| `data/umass_gis.json` | yes | Public building outlines and elevator points from the UMass accessibility map (ArcGIS, 2022 data) |
| `data/out/sin_notices.json` | no | Every notice, normalized. Descriptions are free text and can contain staff names |
| `data/out/closures_official.json` | no | Closures active at evaluation time, in the `Closure` contract (`docs/contracts.md`) |

## Run

```powershell
pip install -r requirements.txt     # or reuse routing/.venv
python parse_sin.py                          # closures active now
python parse_sin.py --at 2026-06-09T09:00    # closures active at a local time
python umass_gis.py                          # re-download GIS data (also: --refresh-gis)
```

Parsing is offline after the first GIS download, so an hourly job keeps working without Wi-Fi.
Re-export the CSV to pick up new notices; notices are posted days to weeks ahead.

## Policy

- A notice blocks a building's elevators for its time window if it mentions elevator work
  (including "may be unavailable"), or if the whole building loses power.
- "Partial" notices (one car at a time) also block, because they rarely say which car.
  `--skip-partial` keeps those elevators open.
- Freight and dumbwaiter work is ignored (`--include-freight` to block anyway).
- Cancelled, superseded and replaced notices are dropped. Duplicate IDs keep the last row.
- Broken dates and times are repaired and flagged (`end_year_fixed`, `end_meridiem_fixed`, ...).
  Uncertain building matches are flagged (`building_unmatched`, `building_ambiguous`).
  These flags are the queue for a later Gemini review pass.

## Closure output

One closure per elevator point in the building (radius 10 m), or one at the building
centroid if the GIS data has no elevator there. Extra fields (`source`, `notice_id`,
`building`, `starts_at`, `severity`) are ignored by the routing engine but useful to the app.
`confirmed_at` is the CSV export time.

The contract has no start time, so only closures active at `--at` are written. Upcoming
notices are in `sin_notices.json`.

## Send to the backend (merge, don't overwrite)

```powershell
$env:CAMPUSNAV_API_URL = "http://127.0.0.1:8000"
$env:CAMPUSNAV_ADMIN_KEY = "<same key as the backend>"
python sync_backend.py --dry-run   # show what would change
python sync_backend.py             # merge into POST /official-reports
```

`POST /official-reports` replaces the whole official list, and other scrapers write to it too.
`sync_backend.py` reads the current list, keeps every entry whose `id` doesn't start with `sin-`,
replaces its own `sin-` entries with every notice in the CSV that hasn't ended yet, and posts the
merged list. Future notices are sent with their `start_time`; the backend only shows them in
`/closures` once they start. If the current list can't be read, nothing is posted.

Known limits:
- Every other writer must also merge (keep entries it doesn't own), or it will erase the `sin-`
  entries on its next run.
- The backend sets `last_confirmed` to the post time on every entry, so reposting another
  source's entries refreshes their "last confirmed" time.
- A writer posting between this script's read and write loses its update until its next run.
