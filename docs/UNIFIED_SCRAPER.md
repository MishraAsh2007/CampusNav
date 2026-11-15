# One command for all CampusNav sources

From the project folder in PowerShell:

```powershell
.\scrape-all.cmd --rules-only
```

This is the main collection command. It runs the existing adapters in dependency
order, continues when an independent source fails, and assembles the results.
It uses the existing saved UMass session. If that session expires, the private
workers report failure and previous data remains available; sign in with
`login-notices.cmd` before the next live refresh.

This remains Role 1/Role 3 work. The collector does not change frontend code or
connect to Role 4's MongoDB Atlas account. It includes existing local community
report records in the private bundle; the separate database service keeps its own
write and API responsibilities.

The entry point is `scripts/scrape_all.py`; orchestration and bundling are in
`campus_notices/all_sources.py`. The individual adapters remain reusable.

## Collected source families

| Stage | What it collects |
| --- | --- |
| `campus-map` | Public UMass building footprints, entrances and mapped elevator points |
| `outdoor-osm` | OSM extract for the expanded residence/campus area |
| `residence-plans` | Authenticated residence-plan inventory and PDFs; unchanged remote versions with intact local hashes reuse existing files |
| `building-catalogs` | Derived central and residence catalogs, using this run's GIS data and cached OSM; preserves manually maintained registry IDs |
| `entrance-evidence` | Additional public UMass door-opener records, dated and compared with the current map; fills nonresidential catalog gaps without overriding newer records |
| `indoor-references` | Library/ILC/Campus Center directories, floor images, restrooms and study-space references |
| `library-elevators` | StackMap floor-local elevator regions and explicitly historical car references |
| `central-plans` | Hospitality images, public PDF references and current official Student Union gallery directions |
| `plan-search` | Private SharePoint document-search results for Student Union, Campus Center and library elevators |
| `building-documents` | Official SharePoint brochures, Old Chapel tour guide and Goodell's original public directory plan |
| `additional-wayfinding` | Builds Old Chapel, North D and Goodell traces only from hash-pinned inspected editions |
| `plan-portals` | Checks explicit drawing/GIS/OSM entrance matches; enables North D's southwest threshold and records unresolved doors |
| `official-notices` | Scraped maintenance notices, rules-first parsing and processed official closures |
| `public-reports` | Configured PVTA/news/social feeds and a private review queue |

Reddit and Facebook still require their configured API credentials. Having one
command does not configure those accounts or turn complaints into confirmed
closures. The spreadsheet remains the notice worker's last fallback after live
scraping and its saved scrape, with its mode exposed in the status report.

## Outputs

- `data/collected_data.json`: combined buildings, active official closures,
  public GIS/source references, public indoor maps and graph/elevation artifact
  references. Each source keeps its own observation time and collection mode.
- `data/scrape_status.json`: per-stage `live`, `derived`, `partial`, `cache` or
  `unavailable`, plus individual feed statuses and artifact hashes/timestamps.
- `data/private/collected_data.json`: private plan inventory, search results,
  building brochures, selected gap-research metadata, external report reviews,
  local community reports and drawing-wayfinding maps.
- `data/private/scrape_logs/`: individual worker output for diagnosis.

These are local collection outputs, not automatically published web endpoints.
Authentication sessions and `.env` files are never copied into either bundle.
Private plans/posts remain in the private bundle. The raw PDFs stay in their
existing source folders and are referenced by their inventory rather than embedded
in JSON. Generated bundles are ignored by Git.

`assembled_at` says when the bundle was created, not when a door or elevator was
confirmed. A cached source retains its old observation time. `official_closures`
is null when the official snapshot is unavailable and an array when it is usable;
an empty array does not establish that every elevator works. Current API stores
remain in their existing paths, so the application does not need to migrate.

## Other ways to run

Combine saved data without making network requests:

```powershell
.\scrape-all.cmd --offline
```

Refresh only selected sources while including other saved datasets in the bundle:

```powershell
.\scrape-all.cmd --rules-only --stage indoor-references --stage library-elevators
```

Keep one worker running, refreshing an hour after each run finishes:

```powershell
.\scrape-all.cmd --rules-only --watch
```

Omit `--rules-only` to allow the existing configured Gemini fallback after rules.
The optional `--rebuild-graphs` also rebuilds the two outdoor walking graphs and
elevation estimates; it needs the `[build]` dependencies and takes longer. Ordinary
collection includes the current graph/elevation artifact references and does not
rebuild them. The OSM map extract and prepared routing graphs have separate dates.

The live acceptance run refreshed the GIS layers, OSM extract, all 218 unchanged
residence PDFs by version/hash reuse, all 155 indoor references, 26 library floor
pages, public feeds and SharePoint search. Maintenance pagination now uses a fresh
saved-session request context for each page and successfully scrapes live.
The retired Student Union business-map PDF URL is unavailable, while its other
central sources are retained. Reddit/Facebook remain unconfigured. Those gaps are
visible as partial status rather than hidden behind a successful process exit.

A partial run still writes usable combined data and reports the gaps. Exit code 1
means none of the requested source families had available data. The command never
starts the application server, rewrites authored indoor routes, enables unreviewed
floor connections or merges the teammate's ground-truth JSON automatically.
