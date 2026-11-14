# Role 3: web scraper

Watches r/umass and a UMass facilities alert page for broken elevators, blocked ramps and closed paths, uses Gemini to turn each post into a closure, and appends it to `closures.json`.

## Status for the Role 3 team (Nov 14, 2026)

Started by Atharva (Role 2) to help out. Everything is in `scraper.py`; nothing outside this folder was changed, so it merges cleanly.

**Tested**

- Live Reddit run: pulled 25 recent r/umass posts and kept 1 that matched a keyword ("Are Field and Grayson still accessible from each other?").
- Error handling, tested with a fake Gemini response (all passed): malformed JSON is retried once and then skipped; API errors are skipped without crashing; off-campus locations are dropped; a corrupt `closures.json` is backed up and a new file is started; duplicates are not added; every saved object has exactly the 8 contract fields.
- Backend upload (`--post-to-backend`), tested with Gemini faked against both backend versions:
  - `backend` branch (newest): Reddit incidents were stored as community reports, and the facilities notice was stored as an official notice with its title and start time. A wrong admin key is rejected (403).
  - `main`: community reports go through the older `/reports` endpoint; the official list is skipped with a clear warning, because `main` has no `/official-reports` yet.
  - A failed facilities fetch leaves the backend's official list untouched.
- Not tested: a real Gemini call. No API key was available on the machine it was written on.

**Where it differs from the original spec**

- **Reddit URL**: `www.reddit.com/r/umass/new.json` and `old.reddit.com` both return 403 (forbidden) to scripts. The script tries both, then falls back to Reddit's RSS feed, which works.
- **SDK**: `google-generativeai` reached end of life on Nov 30, 2025, so it uses the replacement, `google-genai`.
- **Model**: `gemini-1.5-flash` has been shut down. The default is `gemini-3.8-flash`; change it with `GEMINI_MODEL` in `.env`.
- **Locations**: the Gemini prompt includes a list of campus buildings with verified OpenStreetMap coordinates. When Gemini names a known building, the script uses those coordinates instead of its guess.

**Still to do**

1. **Facilities scraper**: `scrape_facilities_page()` is a template. Plug in the real URL (`--facilities-url` or `FACILITIES_URL` in `.env`) and update the CSS selectors marked `TODO`. The official UMass "Current Interruptions" page is a SharePoint page that loads with JavaScript, so plain `requests` sees an empty page; use its list/RSS export or a headless browser.
2. **Run with a real key** (`python scraper.py --sample` is the quickest check) and tune the prompt if Gemini over- or under-reports.
3. **Degraded reports** are kept in `closures.json` but not sent to the backend, which only supports `closed`. If the backend adds a `degraded` status, remove the check in `post_community()` and `official_entries()`.

## Run

```powershell
cd role-3-web-scraper
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # then put your GEMINI_API_KEY in .env

.\.venv\Scripts\python.exe scraper.py              # one pass
.\.venv\Scripts\python.exe scraper.py --loop 300   # every 5 minutes
.\.venv\Scripts\python.exe scraper.py --sample     # parse 4 built-in sample posts, print the JSON
.\.venv\Scripts\python.exe scraper.py --dry-run    # scrape + parse, print instead of writing
.\.venv\Scripts\python.exe scraper.py --facilities-url https://...   # add a facilities page
.\.venv\Scripts\python.exe scraper.py --post-to-backend   # also send results to the backend
```

Without `GEMINI_API_KEY` it still scrapes and lists the matching posts, so you can test the scrapers first.

## Output (`closures.json`)

A JSON array; each run appends new objects:

```json
{
  "lat": 42.38974,
  "lng": -72.52817,
  "radius": 12,
  "type": "elevator",
  "status": "closed",
  "source": "reddit",
  "start_time": "2026-11-14T02:30:00Z",
  "last_confirmed": "2026-11-14T03:00:00Z"
}
```

`type` is `elevator` or `path`, `status` is `closed` or `degraded`, `source` is `reddit` or `official`.

## How it works

1. **Reddit**: tries `www.reddit.com/r/umass/new.json`, then `old.reddit.com`, then the RSS feed. Reddit currently returns 403 to scripts on both JSON URLs (checked Nov 2026), so the RSS fallback is what actually runs. Posts are kept if they mention a keyword (elevator, ramp, closed, construction, wheelchair, curb cut, ...).
2. **Facilities page**: `scrape_facilities_page()` is BeautifulSoup boilerplate; set the URL and adjust the CSS selectors marked `TODO`. The official UMass "Current Interruptions" list is a SharePoint page that renders with JavaScript, so plain `requests` sees an empty page; use its list/RSS export or a headless browser for that one.
3. **Gemini**: each post goes to Gemini with a system prompt that defines an incident, lists known campus buildings with coordinates, and asks for `[]` when the post is not an incident. Gemini's JSON mode plus a Pydantic schema keeps the output in shape.
4. **Checks before writing**: if Gemini names a known building, its coordinates are replaced with the verified ones; anything outside the campus bounding box is dropped; every object is validated against the contract.
5. **Output**: new closures are appended to `closures.json` (atomic write, exact duplicates skipped). `.seen_ids.json` remembers processed posts so reruns don't call Gemini again.

## Error handling

| Problem | What happens |
| --- | --- |
| Reddit 403 / 429 / timeout | Backs off and retries, falls back to RSS, then skips Reddit for this run |
| Gemini returns malformed JSON | Retries once, then skips that post |
| Gemini quota (429) or auth error | Waits and retries on quota; skips on other errors |
| Location off campus | Dropped with a warning |
| `closures.json` is corrupt | Renamed to `closures.json.corrupt-<time>`, a new file is started |
| Any other error in `--loop` mode | Logged; the next cycle still runs |

## Sending results to the backend (`--post-to-backend`)

`closures.json` always keeps the exact Role 3 format above. The backend (`backend/main.py`) is stricter, so `--post-to-backend` converts before sending:

| Scraped as | Sent to | Body |
| --- | --- | --- |
| `source: "reddit"`, `closed` | `POST /community-reports` (falls back to `POST /reports` on the older backend on `main`) | `{lat, lng, type, radius}`; the backend sets the id, times and `community` source |
| `source: "official"`, `closed` | `POST /official-reports` with header `X-Admin-Key` | `{"closures": [{id, title, details, lat, lng, radius, type, start_time}]}` |
| `status: "degraded"` | not sent | the backend only has `closed` |

- **Configuration**: the backend URL comes from `CAMPUSNAV_API_URL` (default `http://127.0.0.1:8000`), or pass it as `--post-to-backend URL`. Official notices need `CAMPUSNAV_ADMIN_KEY` in `.env`, the same value as the backend's.
- **The official list is replaced, not appended.** `POST /official-reports` overwrites the backend's whole official list. So the scraper sends every notice currently on the facilities page, including ones parsed on earlier runs (remembered in `.official_cache.json`). It sends nothing if the page could not be fetched, so a network failure never wipes the list.
- **Ids are stable.** Each notice's `id` is built from the notice text, so re-sending updates notices instead of duplicating them.
- **Each Reddit post is sent once**, because processed posts are remembered in `.seen_ids.json`.

The CampusNav frontend reads the backend's `/closures` feed, so anything sent here shows up on the map within its 5-second poll.
