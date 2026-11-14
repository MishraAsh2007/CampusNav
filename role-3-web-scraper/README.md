# Role 3: web scraper

Watches r/umass and a UMass facilities alert page for broken elevators, blocked ramps and closed paths, uses Gemini to turn each post into a closure, and appends it to `closures.json`.

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

## Changes from the original spec

- **SDK**: uses `google-genai` instead of `google-generativeai`. The old SDK reached end of life on Nov 30, 2025.
- **Model**: defaults to `gemini-3.8-flash`, because `gemini-1.5-flash` has been shut down. Override it with `GEMINI_MODEL`.

## Hooking into the app

- `backend/main.py` currently accepts `source` values `community`, `demo` and `official`, not `reddit`. To feed these closures into the backend, either add `reddit` to its `source` literal or map `reddit` to `community` when loading.
- The CampusNav frontend already reads this shape: `lat`, `lng`, `radius`, `type` and `status` are all it needs.
