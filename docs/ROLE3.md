# Official notices pipeline

This implements Role 3's ingestion, parsing, and caching. The parser uses a finite set of
regex-recognized phrases and explicit service states. It abstains on ambiguity and can ask
Gemini for a structured extraction. Routing and cached-data endpoints never wait for Gemini.

Role 3 now also has a public indoor-source scraper: run `.\refresh-indoor.cmd` to refresh
library floor-plan references, campus room/floor directories, and public ArcGIS restroom
and study-space landmarks. Six sources currently supply 155 references. See
[Indoor mapping](INDOOR_MAPPING.md) for source coverage, graph review/import, and matching
notices to exact building/floor/elevator IDs. Scraped floor references stay non-routable
until their corridor and entrance connections have been mapped and reviewed.
The [source investigation](INDOOR_SOURCE_AUDIT.md) explains the interactive map's limits.
[Guided navigation](GUIDED_NAVIGATION.md) explains how source record IDs and reviewed node
aliases connect those records to the library–ILC backend flow. Scraping never invents
directions or promotes a source point into a walkable connection.

## Run it

Install the optional ingestion dependencies once:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[pipeline,scraper,dev]"
```

Connect your UMass session once, then run a refresh with no AI calls:

```powershell
.\login-notices.cmd
.\refresh-notices.cmd --rules-only
```

The login helper opens a separate Chrome session. Sign in and complete MFA yourself; once
the notices list is visible, press Enter in the terminal. It reads the live list through
`context.request`, which uses the signed-in browser's cookie jar. It then checks a separate
Playwright request context with the saved cookies and browser user agent, verifying the
hourly worker's access before replacing `data/private/sharepoint-session.json`. The saved
state includes cookies scoped to the UMass tenant and parent SharePoint domain, preserving
site-specific paths and cookie attributes. Identity-provider cookies, local storage, and
passwords are excluded. The file is ignored by Git and must not be shared.
For Edge, run `login-notices.cmd --browser msedge` instead. Chrome/Edge are used
from their existing installations; no browser download is needed for those options.

Access is verified by the list API response, not the original tab's URL. The original tab's
cached URL can lag behind manual sign-in, and authentication can finish in a new tab. These
cases must not reject a working session before any request is made.

If the browser shows the notices but verification fails, leave it open. The helper keeps
that session available and writes a safe diagnostic to
`data/private/sharepoint-login-diagnostic.json`, containing the failed stage/status rather
than cookie values, request headers, or notice contents. HTTP 401, a redirect, HTTP 403,
and a connection failure are reported separately. A 403 may reflect API permissions or an
access policy even if the page is visible; the helper does not tell you to sign in repeatedly.
Press Enter to retry, `r` to load an updated verification helper and retry while preserving
the same open browser session, or `q` to cancel. A failed check never
replaces the previously verified session. No tenant security settings are changed.

Each normal refresh follows this order:

1. Fetch the authenticated live SharePoint list.
2. If it fails, use the last complete successful scrape in `data/private/sharepoint-notices.json`.
3. If no valid scrape cache exists, use `~/Downloads/Book1.xlsx` as a fallback. Change that
   location with `--fallback-spreadsheet PATH`.
4. If none are usable, keep the previously published closures and mark the refresh failed.

Fallbacks are labelled `cache` or `spreadsheet_fallback`; they preserve source observation
timestamps and mark the API status stale. A missing/expired session is a fallback condition,
not evidence of an empty list. The scraper and fallback behavior are tested with HTTP
fixtures. The authenticated live fetch has now also succeeded with the saved user session:
1,095 distinct notices. After importing official map locations, the integration refresh
published two upcoming elevator-inspection notices, with one item still requiring review.
See [data sources and expected outputs](../DATA_SOURCES.md) for coverage and interpretation.

## Authentication and hosting

```text
UMass SharePoint -> private scheduled scraper -> saved processed notices -> backend API -> students
```

Only the scraper needs source credentials. Students and the map frontend never receive the
SharePoint session. The current API serves processed closures and source-status metadata;
the private notice cache and login files are not HTTP routes.

For the hackathon, one operator signs in and leaves `refresh-notices.cmd --watch` running.
Session expiry marks the source stale and uses the last complete scrape. Expired closures
are still excluded; a failed refresh cannot reset confirmation timestamps. This is not an
unattended production login system. A teammate running a separate ingestion worker must
sign in with their own UMass account that can access the list; app users need no such access.

For hosting, arrange approved application access with UMass. Microsoft supports application
authentication for background services and read permission restricted to a selected list/site.
It requires tenant consent and a resource permission grant. Agree with the source owner which
data can be distributed. A future worker can use that service identity; the frontend and
routing contract remain unchanged. This code currently implements saved browser sessions only,
not Microsoft Graph application authentication or deployment.

References: [Microsoft application authentication](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
and [selected SharePoint permissions](https://learn.microsoft.com/en-us/graph/permissions-selected-overview).

## Optional Gemini fallback

Enable Gemini fallback by setting `GEMINI_API_KEY` in a local `.env` file, then omit `--rules-only`:

```powershell
.\refresh-notices.cmd
```

The supplied key is already stored locally for this workspace. `.env`, source reviews,
model-response caches, and generated production snapshots are ignored by Git. The key is
never printed. `GEMINI_MODEL` can override the default `gemini-3.5-flash-lite`.

The application was tested with mocked Gemini responses. A live attempt in the agent's
environment failed with `ConnectError` before a usable response, so key validity and live
model access still need verification from a terminal with network access.

To exercise parsing, publishing, and review without the real export or Gemini:

```powershell
.\refresh-notices.cmd --demo
```

The demo writes only to `data/private/demo_official_*.json`, with explicit synthetic markers
and a fixed clock. It produces one mapped synthetic elevator closure and one review item.
It does not publish its fake outage to the real official-closure endpoint.

## Parsing decisions

| Input | Result |
| --- | --- |
| Elevator is out of service; explicit interval | Rules: closed |
| Car(s) may be unavailable during the test | Rules: degraded inspection |
| Path has reopened | Rules: working/restored |
| Elevator will not be closed | Abstain: negation needs interpretation |
| Only one of several elevators is unavailable | Abstain: ambiguous asset scope |
| Work occurs daily or in multiple phases | Abstain: recurring intervals need interpretation |
| Water shutdown without accessibility impact | Ignore |
| Any outage without a unique reviewed location | Review; no guessed coordinates |

Status phrases must attach to the accessibility asset using a bounded subject/verb
vocabulary. A broken water pipe in an elevator room is not automatically an elevator outage.
This is a conservative rules parser, not a general natural-language DFA. Unsupported wording
does not mean “working”: it goes to Gemini or the review queue.

Dates and clock times in XLSX/CSV columns are parsed directly in `America/New_York`, including
daylight-saving offsets. Missing or ambiguous clock times are not replaced with midnight.
Explicit ISO intervals in text are supported by the rules. Gemini can extract other explicit
intervals; relative or unclear dates stay unresolved.

Gemini is called only after the rules abstain. A prompt version, model name, source content,
and candidate location list key the extraction cache. Re-fetching unchanged text reuses its
cached extraction. The default budget is at most 25 new calls per refresh, configurable with
`--max-gemini-calls`. Requests have a timeout and bounded retries. A timeout, invalid response,
authentication error, or call-budget failure preserves the previous published snapshot.

## Source support

- Authenticated SharePoint: read-only REST GET requests to the maintenance list identified
  in the user's IQY export. The scraper discovers internal field names, reads selected direct
  values, follows pagination, and validates complete responses before caching. The tenant's
  `FieldValuesAsText` expansion omitted custom columns. UTC date values are converted back
  to campus-local dates before combining the separate clock-time fields. It fetches
  the whole list, then the pipeline filters expired notices and the 30-day lookahead; it does
  not rely on the browser view's current filter. It never edits the university list.
- UMass XLSX/CSV exports: reads `DOC ID#`, `Building`, date/time columns, `Desc`, and service
  categories. Contact columns are excluded; emails and standard phone formats in descriptions
  are redacted before parsing. Workbook contents are never modified.
- HTML files and explicit HTTPS notice URLs: BeautifulSoup extracts main content and removes
  navigation, scripts, and forms. Redirects and sign-in pages are errors, not empty success.
- Text PDFs: pypdf extracts text; scanned PDFs need OCR or a text export first. Encryption,
  oversized files, and empty extraction are reported as failures.
- Plain text and normalized JSON notices: useful for teammate exports and offline demos.

Use `--sources path/to/sources.json` for several sources. Paths are relative to the config
file unless absolute. Start from `examples/role3/sources.example.json` and replace its fallback path.
Example entries, to include in its `sources` array:

```json
[
  {"id": "maintenance-export", "kind": "xlsx", "path": "C:/path/to/Book1.xlsx", "sheet": "query"},
  {"id": "construction-notice", "kind": "html", "path": "notice.html"},
  {"id": "construction-pdf", "kind": "pdf", "path": "notice.pdf"},
  {"id": "transit-alert", "kind": "text", "path": "transit-alert.txt"}
]
```

For a public page, use `kind: "url"`, an HTTPS `url`, and optionally a CSS `selector` such
as `main`. Configure actual notice pages rather than a general landing page. UMass's public
[construction/service-interruption page](https://www.umass.edu/facilities/construction-service-interruption-notices)
describes submission procedures; it is not a live outage feed. The supplied SharePoint list
is the default primary source. Public transit feeds and complaint discovery use the separate
[public reports pipeline](PUBLIC_REPORTS.md), which keeps unverified claims out of routing closures.
`--spreadsheet PATH` remains an explicit offline-only diagnostic mode;
normal runs without that flag always try the scraper first.

Duplicate document numbers are disambiguated with building and start information. Identical
rows are deduplicated; conflicting rows with the same identity are flagged for review.

## Add reviewed locations

`data/location_registry.json` deliberately starts empty. Add only coordinates tied to a
specific asset, with evidence supporting the location and its radius. Each entry requires:

| Field | Meaning |
| --- | --- |
| `id`, `name`, `type` | Stable asset identifier, label, and elevator/ramp/path type |
| `lat`, `lng`, `radius` | Reviewed asset position and affected radius in meters |
| `building_aliases` | Exact building phrases, such as a full name and abbreviation |
| `asset_phrases` | Phrases identifying that asset, such as an elevator number or entrance |
| `reviewed` | Set true after checking the location and scope |
| `synthetic` | False for real assets; demo locations cannot enter production |
| `evidence` | Map reference, source URL, or verification note supporting the mapping |

`examples/role3/locations.json` demonstrates the schema using fake data. Both a building alias
and an asset phrase must match the source. A building center alone does not establish which
elevator is affected. Gemini can select among supplied matching IDs but cannot supply arbitrary
coordinates. The current OSM graph has no elevator edges; those must also be mapped in Role 1
before a real elevator closure can alter a route.

After filling the registry, rerun the same refresh. Resolved candidates become contract-valid
closures. No live AI call is required to reprocess an unambiguous rules-parsed notice.

## Outputs and freshness

- `data/official_snapshot.json`: authoritative atomic snapshot, including provenance and counts.
- `data/official_closures.json`: derived list for Role 4, including scheduled closures. Role 4
  should honor time intervals; the HTTP endpoint below returns only active ones.
- `data/official_snapshot.review.json`: unresolved notices, reasons, and extracted candidates.
- `data/official_snapshot.status.json`: last refresh attempt and AI call/cache-hit counts.

One writer lock prevents overlapping refreshes from modifying the same snapshot. If a process
is forcibly terminated and leaves a `.lock`, verify that it has stopped before removing that
specific lock file. A network or parsing failure never replaces the previous snapshot with an
empty list. A schema-validated authenticated empty list is permitted, but disappears-from-list
alone does not clear an earlier open-ended closure. An unresolved revision retains its previous
known closures and their old timestamps.
An explicit restoration can clear older official closures for the same reviewed asset/source.

`last_confirmed` means the official source was observed, not that a person inspected an elevator.
The provenance field `confirmation_kind` is `source_observed`. For spreadsheet exports, it uses
the file's modification timestamp, not the time of each re-import. UI wording should say
“Official notice last observed…” rather than imply a physical confirmation.

## Backend handoff and browser access

Run `.\start-server.cmd`, then open http://127.0.0.1:8000 for route and notice status buttons.
Detailed API documentation is at `/docs`.

- `GET /official-closures`: active cached closures in the shared contract. It filters expired
  notices at read time even when refresh is offline.
- `GET /official-closures/status`: whether data is available, stale, synthetic, or has review
  items; includes source observation times, `source_status` with live/fallback provenance,
  and the last refresh outcome.
- Missing or corrupt snapshots return 503 instead of claiming there are no closures.
- Response headers `X-Closures-Stale`, `X-Closures-Status`, and `X-Closures-Demo` are exposed to
  the browser via CORS. A review queue with an empty closure list does not establish “all clear.”

Role 4 merges this official list with MongoDB community reports at its own `/closures` endpoint.
That backend still owns report precedence, TTL, and persistence. No MongoDB credentials are
required for this pipeline.

## Hourly refresh

```powershell
.\refresh-notices.cmd --watch
```

Keep that terminal open; Ctrl+C stops the loop. The default interval is 3,600 seconds. To use
Windows Task Scheduler instead, run `refresh-notices.cmd` hourly with the same arguments
without `--watch`, and set its working directory to the project. No scheduled task has been
registered automatically. SharePoint is fetched on every run. If its saved session expires,
the loop uses fallback data and tells you to rerun `login-notices.cmd`. A spreadsheet fallback
remains a static export; repeating it cannot refresh its timestamps.

## Validation and pitch

The automated suite covers unambiguous rules, abstention, subject association, negation,
restoration, DST, duplicate IDs, source redaction, sign-in redirects, Gemini caching/schema
validation, hallucinated locations/evidence, atomic failure fallback, cached API responses,
and a parsed closure causing the expected route detour. Scraper tests cover pagination,
schema validation, redirect/login failures, partial-fetch preservation, cookie scoping,
live-first precedence, cache/export fallback, and unchanged freshness on fallback.

The first real import normalized 1,098 exported rows into 1,095 distinct notices. At import
time, 1,087 were expired. Three notices needed review; no unverified coordinates were published.
These counts describe that export and time, not a claim about every current campus outage.

See [the Devpost and demo draft](DEMO_PITCH.md). Validate a live Gemini fallback and fill the
real location registry before describing those parts as operational in the submission.

Implementation references: [SharePoint list REST API](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/working-with-lists-and-list-items-with-rest),
[SharePoint pagination](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/use-odata-query-operations-in-sharepoint-rest-requests),
[Playwright authentication state](https://playwright.dev/python/docs/auth),
[Google Gen AI SDK](https://googleapis.github.io/python-genai/),
[structured output](https://ai.google.dev/gemini-api/docs/structured-output),
[model configuration](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[openpyxl read-only mode](https://openpyxl.readthedocs.io/en/stable/optimized.html), and
[pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
