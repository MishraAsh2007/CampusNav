# Public reports and transit alerts

For how this worker fits into routing, official notices and indoor maps, see
[the full application guide](APPLICATION_GUIDE.md).

This worker discovers possible accessibility issues for review. A bus detour, complaint,
or old article does not establish that a walking path or elevator is currently unavailable.

## Run and inspect

```powershell
.\refresh-reports.cmd --rules-only
.\start-server.cmd
```

Open http://127.0.0.1:8000 and expand **Public-source reports awaiting review** in the planner.
The backend diagnostic page at `/backend` also has **Show discovered reports**. For hourly refreshes,
run `refresh-reports.cmd --rules-only --watch` in a separate terminal. Ctrl+C stops it.
Remove `--rules-only` to use the local Gemini key after rules abstain, with a budget of
ten new calls per refresh. A failed optional parser leaves the report in review.

- `GET /external-reports`: saved, unexpired candidates; no network or LLM calls.
- `GET /external-reports/status`: source availability and last successful fetch.
- `data/private/external_reports.json`: local snapshot, ignored by Git.
- `--demo`: writes a separate synthetic snapshot, not the API's real report data.

## Sources

Configure `data/public_sources.json` or pass `--sources PATH`.

| Source | Support and current state |
| --- | --- |
| PVTA | Official HTML alert embed; filters UMass route badges. Successfully fetched. |
| Daily Collegian | Public RSS; recent accessibility/transit keyword matches. Successfully fetched. |
| Reddit | Latest r/umass posts and comments through the API. Needs authorized app credentials. |
| Facebook | Configured Page feed through the Graph API. Needs a Page ID and authorized token. |
| Other sources | RSS/Atom feeds and public HTML with per-report selectors. |

The first live refresh kept three PVTA reports for review. Two football-detour titles refer
to different routes (34 and 35). A successfully fetched feed may contain no recent matching
reports. These feeds do not provide complete campus coverage.

### Social API configuration

Add credentials to the ignored local `.env`, not the source JSON or frontend:

```dotenv
REDDIT_ACCESS_TOKEN=your-authorized-app-token
REDDIT_USER_AGENT=your-registered-app-user-agent
FACEBOOK_PAGE_ACCESS_TOKEN=your-authorized-page-token
```

Set Facebook's `page_id` in the source configuration. Access depends on the app/token's
permissions for that Page; arbitrary groups and private profiles are not supported. Reddit
requires approved API access. Tokens travel in authorization headers, never URL parameters.
Token issuance/renewal and app registration are not implemented. HTTP 401/403/429 results
in explicit source failure and cache fallback, without repeated retries or alternate scraping
to get around access restrictions.

References: [Reddit data access](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data),
[Reddit API](https://www.reddit.com/dev/api/), and
[Facebook Page feed](https://developers.facebook.com/docs/graph-api/reference/page/feed/).

### Another public source

An RSS entry needs `id`, `kind: "rss"`, an HTTPS `url`, and `authority` (`official`,
`publisher`, or `community`). An HTML entry also needs `item_selector`; optional
`title_selector`, `text_selector`, `link_selector`, and `time_selector` locate fields inside
each report. A missing layout is an error; an `empty_selector` may identify a genuine empty
feed. Login pages and redirects are not accepted as empty feeds. Source URLs are trusted
operator configuration, not user-submitted URLs. This is not an arbitrary-URL proxy.

## Interpretation and freshness

Candidates include a permalink, source authority, text, topics, `published_at`, `first_seen_at`,
`last_seen_at`, and `expires_at`. Contacts and social handles in text are redacted. Publication
time remains null when unknown. Seeing an alert today does not prove it began today.

Rules extract clear service states; Gemini optionally handles ambiguous wording. Any parsed
location must reference the reviewed registry; the parser never supplies new coordinates.
Every report has `review_status: "needs_review"` and `routing_eligible: false`, including clear
claims. There is no automatic promotion or approval endpoint yet. Role 4 must validate asset,
timing, and evidence before creating a closure; restoration claims also need review.

Default retention is 24 hours, bounded by both publication and first observation. Repeated
fetches do not extend expiry. IDs of expired posts still present in a feed prevent them
from reappearing as newly seen. Successful feeds replace their previous candidates, dropping
removed posts. A failed source preserves its timestamps and unexpired candidates while other
sources continue. Expiry also runs when the API reads the snapshot.

The worker reads bounded recent feeds, not historical archives. Sources are limited to 5 MB
and 200 items; social adapters read at most 100 posts and 100 Reddit comments per refresh.
Missing coverage and unresolved reports never imply campus is all clear.

Sources: [PVTA alerts](https://www.pvta.com/bus_service/service_alerts___detours.php),
[PVTA alert embed](https://pvta.us/swiftly/RevizeAlerts2.php),
[Daily Collegian feed](https://dailycollegian.com/feed/).
