#!/usr/bin/env python3
"""
CampusNav Role 3: accessibility incident ingestion.

  1. Scrape r/umass and a UMass facilities alert page for posts about broken elevators, blocked ramps,
     closed paths and construction.
  2. Ask Gemini to turn each candidate post into structured closures (or nothing, if it is not an incident).
  3. Append valid closures to closures.json.

Usage:
  python scraper.py                      # one pass: Reddit + facilities page -> closures.json
  python scraper.py --loop 300           # repeat every 5 minutes
  python scraper.py --dry-run            # print what would be written, change nothing
  python scraper.py --sample             # run the Gemini parser on built-in sample posts (no scraping)
  python scraper.py --facilities-url URL # scrape a real facilities alert page
  python scraper.py --post-to-backend    # also send results to the CampusNav backend

Environment (or a .env file next to this script):
  GEMINI_API_KEY       required for parsing; without it the script scrapes and reports candidates only
  GEMINI_MODEL         default gemini-3.8-flash (gemini-1.5-flash has been shut down)
  CAMPUSNAV_API_URL    backend for --post-to-backend, default http://127.0.0.1:8000
  CAMPUSNAV_ADMIN_KEY  must match the backend's key to update official notices
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "closures.json"
SEEN_FILE = HERE / ".seen_ids.json"

USER_AGENT = "CampusNav/1.0 (HackUMass accessibility routing project; contact via GitHub MishraAsh2007/CampusNav)"
REDDIT_JSON_URLS = [
    "https://www.reddit.com/r/umass/new.json",
    # www.reddit.com often answers 403 to scripts; old.reddit serves the same JSON
    "https://old.reddit.com/r/umass/new.json",
]
REDDIT_RSS_URL = "https://www.reddit.com/r/umass/new/.rss"

KEYWORDS = [
    "elevator", "lift", "broken", "out of order", "out of service", "closed", "closure",
    "construction", "ramp", "blocked", "detour", "wheelchair", "accessible", "accessibility",
    "automatic door", "door opener", "curb cut", "icy", "flooded",
]
KEYWORD_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in KEYWORDS) + r")\b", re.IGNORECASE)

# Central-campus bounding box; anything outside is a hallucinated or off-campus location
CAMPUS_BBOX = (42.380, -72.540, 42.400, -72.515)  # south, west, north, east

# Building centroids from OpenStreetMap (same positions the CampusNav map uses)
BUILDINGS: dict[str, tuple[float, float]] = {
    "Lincoln Campus Center": (42.39180, -72.52702),
    "Student Union": (42.39087, -72.52760),
    "Integrative Learning Center (ILC)": (42.39104, -72.52590),
    "W.E.B. Du Bois Library": (42.38974, -72.52817),
    "Goodell Hall": (42.38871, -72.52922),
    "Morrill Science Center": (42.38990, -72.52450),
    "Hasbrouck Laboratory": (42.39179, -72.52589),
    "Worcester Dining Commons": (42.39328, -72.52509),
    "Herter Hall": (42.38724, -72.52717),
    "Boyden Gymnasium": (42.38639, -72.53047),
    "Recreation Center": (42.38883, -72.53168),
    "Whitmore Administration Building": (42.38595, -72.52670),
    "Campus Pond": (42.38947, -72.52653),
    "Campus Center Parking Garage": (42.39120, -72.52906),
}

log = logging.getLogger("campusnav.scraper")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class RawItem:
    """One piece of scraped text waiting for the LLM."""
    uid: str  # stable id for de-duplication
    source: Literal["reddit", "official"]
    text: str
    posted_at: datetime
    url: str


class Closure(BaseModel):
    """The output contract written to closures.json."""
    lat: float
    lng: float
    radius: int = Field(gt=0, le=500)
    type: Literal["elevator", "path"]
    status: Literal["closed", "degraded"]
    source: Literal["official", "reddit"]
    start_time: str
    last_confirmed: str


class ExtractedIncident(BaseModel):
    """What Gemini returns per incident. Converted to Closure after validation."""
    title: str = Field(default="", description="Short headline naming the place and the problem")
    building: str = Field(description="Exact building name from the list, or 'unknown'")
    lat: float
    lng: float
    radius: int
    type: Literal["elevator", "path"]
    status: Literal["closed", "degraded"]
    start_time: str = Field(description="ISO 8601 UTC; when the problem started, else the post time")


# ---------------------------------------------------------------------------
# Step 1: scrapers
# ---------------------------------------------------------------------------

def _get(url: str, *, params: dict | None = None, retries: int = 3, timeout: int = 15) -> requests.Response | None:
    """GET with a polite User-Agent and backoff on 429/5xx. Returns None instead of raising."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        except requests.RequestException as exc:
            log.warning("GET %s failed (%s)", url, exc)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
            log.warning("GET %s -> HTTP %s, retrying in %.0fs", url, resp.status_code, wait)
            time.sleep(min(wait, 60))
            continue
        if resp.status_code != 200:
            log.info("GET %s -> HTTP %s", url, resp.status_code)
            return None
        return resp
    log.warning("GET %s gave up after %d attempts", url, retries)
    return None


def fetch_reddit_posts(limit: int = 50) -> list[RawItem]:
    """Latest r/umass posts that mention an accessibility keyword."""
    posts: list[RawItem] = []
    for url in REDDIT_JSON_URLS:
        resp = _get(url, params={"limit": limit, "raw_json": 1})
        if not resp:
            continue
        try:
            children = resp.json()["data"]["children"]
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("Unexpected Reddit JSON from %s: %s", url, exc)
            continue
        for child in children:
            d = child.get("data", {})
            text = f"{d.get('title', '')}\n\n{d.get('selftext', '')}".strip()
            posts.append(RawItem(
                uid=f"reddit:{d.get('id')}",
                source="reddit",
                text=text,
                posted_at=datetime.fromtimestamp(float(d.get("created_utc", time.time())), tz=timezone.utc),
                url="https://www.reddit.com" + d.get("permalink", ""),
            ))
        log.info("Reddit: %d posts from %s", len(posts), url)
        break
    else:
        posts = _fetch_reddit_rss()

    matched = [p for p in posts if KEYWORD_RE.search(p.text)]
    log.info("Reddit: %d of %d posts mention an accessibility keyword", len(matched), len(posts))
    return matched


def _fetch_reddit_rss() -> list[RawItem]:
    """Last resort when both JSON endpoints are blocked: the Atom feed."""
    resp = _get(REDDIT_RSS_URL)
    if not resp:
        log.warning("Reddit unavailable (JSON and RSS both failed); skipping this run")
        return []
    soup = BeautifulSoup(resp.content, "xml")
    items: list[RawItem] = []
    for entry in soup.find_all("entry"):
        title = entry.find("title").get_text(strip=True) if entry.find("title") else ""
        content = entry.find("content")
        body = BeautifulSoup(content.get_text(), "html.parser").get_text(" ", strip=True) if content else ""
        updated = entry.find("updated")
        try:
            posted = datetime.fromisoformat(updated.get_text(strip=True)) if updated else datetime.now(timezone.utc)
        except ValueError:
            posted = datetime.now(timezone.utc)
        link = entry.find("link")
        items.append(RawItem(
            uid=f"reddit:{entry.find('id').get_text(strip=True) if entry.find('id') else title}",
            source="reddit",
            text=f"{title}\n\n{body}",
            posted_at=posted,
            url=link.get("href", "") if link else "",
        ))
    log.info("Reddit RSS: %d posts", len(items))
    return items


# Set only when the facilities page was actually fetched this run. The backend replaces its official list
# wholesale, so an empty list must never be sent after a failed fetch (it would wipe every notice).
facilities_fetched_ok = False


def scrape_facilities_page(url: str | None) -> list[RawItem]:
    """
    Boilerplate for a UMass facilities alert page. Plug in the real URL and adjust the selectors.

    Note: the official "Current Interruptions" list is a SharePoint page that renders with JavaScript,
    so requests + BeautifulSoup will see an empty shell. If that is the page you need, use its RSS/list
    export URL or a headless browser instead.
    """
    global facilities_fetched_ok
    facilities_fetched_ok = False
    if not url:
        log.info("Facilities: no URL configured (--facilities-url); skipping")
        return []
    resp = _get(url)
    if not resp:
        return []
    facilities_fetched_ok = True
    soup = BeautifulSoup(resp.text, "html.parser")

    # TODO: replace these selectors with the real page's structure.
    # Typical alert pages wrap each notice in an <article>, a list item, or a table row.
    candidates = soup.select("article, .alert, .notice, .views-row, li.notice, table tr")
    if not candidates:
        candidates = [soup.body] if soup.body else []

    items: list[RawItem] = []
    for node in candidates:
        text = node.get_text(" ", strip=True)
        if len(text) < 20 or not KEYWORD_RE.search(text):
            continue
        # Try to find a date in the notice; fall back to now
        posted = datetime.now(timezone.utc)
        time_tag = node.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                posted = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))
            except ValueError:
                pass
        items.append(RawItem(
            uid="official:" + hashlib.sha1(text.encode()).hexdigest()[:16],
            source="official",
            text=text[:4000],
            posted_at=posted,
            url=url,
        ))
    log.info("Facilities: %d matching notices on %s", len(items), url)
    return items


# ---------------------------------------------------------------------------
# Step 2: Gemini parser
# ---------------------------------------------------------------------------

def _system_prompt() -> str:
    gazetteer = "\n".join(f"- {name}: {lat:.5f}, {lng:.5f}" for name, (lat, lng) in BUILDINGS.items())
    return f"""You extract accessibility incidents at UMass Amherst from student posts and official notices.

An incident is something that blocks or hinders people using wheelchairs, crutches or other mobility aids:
a broken or out-of-service elevator, a closed or blocked ramp, path, sidewalk or curb cut, construction
fencing across a walkway, or a broken automatic door opener.

Return a JSON array. Return [] if the text is not about a current physical incident on campus
(complaints about dining, parking tickets, jokes, questions about classes, events, and resolved
issues are NOT incidents).

For each incident return an object with exactly these fields:
- title: a short plain headline (under 80 characters) naming the place and the problem
- building: the matching name from the list below, or "unknown"
- lat, lng: decimal degrees. Use the building's coordinates from the list. If the text names a place not
  in the list, estimate its position on the UMass Amherst campus as best you can. Never invent a
  location outside campus.
- radius: integer metres. 10-15 for a single elevator or door, 20-40 for a path segment, up to 80 for a
  large construction zone.
- type: "elevator" for elevators and lifts; "path" for everything else (ramps, paths, doors, construction).
- status: "closed" if it cannot be used at all; "degraded" if usable with difficulty (slow, partly
  blocked, icy, one of several doors broken).
- start_time: ISO 8601 UTC. When the text says the problem started; otherwise the post time given below.

Known campus locations (lat, lng):
{gazetteer}

Output only the JSON array. No markdown, no commentary."""


_client = None


def _gemini_client():
    global _client
    if _client is None:
        from google import genai  # imported lazily so scraping works without the SDK configured
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.DOTALL)
    return s


@dataclass
class Parsed:
    """A validated closure plus the headline the backend needs for official notices."""
    closure: Closure
    title: str


def parse_with_gemini(item: RawItem, model: str) -> list[Closure]:
    """Ask Gemini for incidents in one scraped item. Returns [] on any failure, never raises."""
    return [p.closure for p in parse_item(item, model)]


def parse_item(item: RawItem, model: str) -> list[Parsed]:
    """Same as parse_with_gemini, keeping Gemini's headline for each closure."""
    from google.genai import types

    prompt = (
        f"Source: {'official UMass notice' if item.source == 'official' else 'r/umass Reddit post'}\n"
        f"Posted at (UTC): {item.posted_at.astimezone(timezone.utc).isoformat()}\n"
        f"URL: {item.url}\n\n"
        f"Text:\n{item.text[:6000]}"
    )
    config = types.GenerateContentConfig(
        system_instruction=_system_prompt(),
        response_mime_type="application/json",
        response_schema=list[ExtractedIncident],
        temperature=0.1,
    )

    for attempt in range(2):
        try:
            resp = _gemini_client().models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:  # network, quota, auth, model errors
            msg = str(exc)
            log.warning("Gemini call failed for %s: %s", item.uid, msg[:200])
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                time.sleep(10 * (attempt + 1))
                continue
            return []

        raw = resp.text or ""
        try:
            data = json.loads(_strip_fences(raw))
            if isinstance(data, dict):
                data = [data]
            incidents = [ExtractedIncident.model_validate(x) for x in data]
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            log.warning("Gemini returned malformed JSON for %s (attempt %d): %s | %r", item.uid, attempt + 1, exc, raw[:200])
            continue
        out: list[Parsed] = []
        for inc in incidents:
            c = _to_closure(inc, item)
            if c is not None:
                title = " ".join(inc.title.split())[:120] or ("Elevator out of service" if c.type == "elevator" else "Path blocked")
                out.append(Parsed(c, title))
        return out
    return []


def _to_closure(inc: ExtractedIncident, item: RawItem) -> Closure | None:
    lat, lng = inc.lat, inc.lng
    # Prefer our verified coordinates when Gemini names a known building
    for name, coords in BUILDINGS.items():
        if inc.building.lower() == name.lower():
            lat, lng = coords
            break
    s, w, n, e = CAMPUS_BBOX
    if not (s <= lat <= n and w <= lng <= e):
        log.warning("Dropping incident from %s: location %.5f,%.5f is off campus", item.uid, lat, lng)
        return None
    start = _iso(inc.start_time, fallback=item.posted_at)
    try:
        return Closure(
            lat=round(lat, 6),
            lng=round(lng, 6),
            radius=max(5, min(int(inc.radius), 500)),
            type=inc.type,
            status=inc.status,
            source=item.source,
            start_time=start,
            last_confirmed=_iso(None, fallback=item.posted_at),
        )
    except ValidationError as exc:
        log.warning("Dropping invalid closure from %s: %s", item.uid, exc)
        return None


def _iso(value: str | None, fallback: datetime) -> str:
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return fallback.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Step 3: output
# ---------------------------------------------------------------------------

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}")
        log.error("%s is unreadable (%s); moving it to %s and starting fresh", path.name, exc, backup.name)
        try:
            path.rename(backup)
        except OSError:
            pass
        return default


def _write_json_atomic(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic on the same filesystem: a crash never leaves half a file


def append_closures(path: Path, closures: list[Closure]) -> int:
    """Append closures to the JSON array in `path`, skipping exact duplicates. Returns how many were added."""
    existing = _load_json(path, [])
    if not isinstance(existing, list):
        log.error("%s does not contain a JSON array; not touching it", path)
        return 0
    seen = {json.dumps(x, sort_keys=True) for x in existing}
    added = 0
    for c in closures:
        d = c.model_dump()
        key = json.dumps(d, sort_keys=True)
        if key not in seen:
            existing.append(d)
            seen.add(key)
            added += 1
    if added:
        _write_json_atomic(path, existing)
    return added


# ---------------------------------------------------------------------------
# Optional: send results to the CampusNav backend (backend/main.py)
# ---------------------------------------------------------------------------
#
# closures.json keeps the exact Role 3 contract. The backend's API is stricter, so this maps onto it:
#   reddit   -> POST /community-reports {lat, lng, type, radius}   (backend sets id, times, status=closed)
#              falls back to POST /reports on the older backend that is on main
#   official -> POST /official-reports {"closures": [...]} with X-Admin-Key. This REPLACES the whole
#              official list, so it is only sent after a successful facilities fetch, and it always
#              contains every notice currently on the page (cached in .official_cache.json).
#   degraded -> not sent: the backend only has "closed", and the router would treat it as impassable.

OFFICIAL_CACHE = HERE / ".official_cache.json"


def _post(url: str, body, headers: dict | None = None) -> requests.Response | None:
    try:
        return requests.post(url, json=body, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=15)
    except requests.RequestException as exc:
        log.warning("POST %s failed (%s)", url, exc)
        return None


def post_community(base: str, parsed: list[Parsed]) -> int:
    sent = 0
    for p in parsed:
        c = p.closure
        if c.status != "closed":
            log.info("Backend: not sending degraded report %r (backend only supports closed)", p.title)
            continue
        body = {"lat": c.lat, "lng": c.lng, "type": c.type, "radius": c.radius}
        resp = _post(f"{base}/community-reports", body)
        if resp is not None and resp.status_code in (404, 405):
            resp = _post(f"{base}/reports", body)  # older backend on main
        if resp is not None and resp.status_code == 201:
            sent += 1
        else:
            log.warning("Backend rejected community report %r: %s", p.title, _describe(resp))
    return sent


def official_entries(item: RawItem, parsed: list[Parsed]) -> list[dict]:
    """Backend OfficialNotice objects for one facilities notice. Ids are stable across runs."""
    entries = []
    for n, p in enumerate(parsed):
        c = p.closure
        if c.status != "closed":
            continue
        entries.append({
            "id": f"{item.uid}-{n}",
            "title": p.title,
            "details": item.text[:500],
            "lat": c.lat,
            "lng": c.lng,
            "radius": c.radius,
            "type": c.type,
            "start_time": c.start_time,
        })
    return entries


def post_official(base: str, admin_key: str, entries: list[dict]) -> bool:
    resp = _post(f"{base}/official-reports", {"closures": entries}, headers={"X-Admin-Key": admin_key})
    if resp is not None and resp.status_code == 200:
        return True
    hint = ""
    if resp is not None and resp.status_code == 404:
        hint = " (this backend has no /official-reports yet; it is on the 'backend' branch)"
    elif resp is not None and resp.status_code in (403, 503):
        hint = " (check CAMPUSNAV_ADMIN_KEY matches the backend's)"
    log.warning("Backend rejected official list: %s%s", _describe(resp), hint)
    return False


def _describe(resp: requests.Response | None) -> str:
    if resp is None:
        return "no response"
    return f"HTTP {resp.status_code} {resp.text[:200]}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

SAMPLE_ITEMS = [
    RawItem("sample:1", "reddit", "Elevator in the Du Bois library lobby is broken AGAIN. Had to wait 20 min for staff to take me up in the freight one.", datetime.now(timezone.utc), "sample"),
    RawItem("sample:2", "reddit", "PSA: the ramp on the west side of the ILC is fenced off for construction, go around through the south entrance", datetime.now(timezone.utc), "sample"),
    RawItem("sample:3", "reddit", "Is Worcester dining closed on Sunday nights?", datetime.now(timezone.utc), "sample"),
    RawItem("sample:4", "official", "Service Interruption: Campus Center concourse elevator out of service 11/14 8:00 AM - 11/15 5:00 PM for hydraulic repair.", datetime.now(timezone.utc), "sample"),
]


def run_once(args) -> int:
    if args.sample:
        items = SAMPLE_ITEMS
        official_complete = True  # the sample notices stand in for a full facilities page
    else:
        items = fetch_reddit_posts(args.limit) + scrape_facilities_page(args.facilities_url)
        official_complete = facilities_fetched_ok

    seen_ids: list[str] = [] if args.sample else _load_json(SEEN_FILE, [])
    if not isinstance(seen_ids, list):
        seen_ids = []
    new_items = [i for i in items if i.uid not in seen_ids]
    log.info("%d new candidate items (%d already processed)", len(new_items), len(items) - len(new_items))

    if not os.environ.get("GEMINI_API_KEY"):
        log.warning("GEMINI_API_KEY is not set: listing candidates without parsing")
        for i in new_items:
            print(f"- [{i.source}] {i.text.splitlines()[0][:100]}  ({i.url})")
        return 0

    writing = not (args.dry_run or args.sample)
    official_cache: dict = {} if args.sample else _load_json(OFFICIAL_CACHE, {})
    if not isinstance(official_cache, dict):
        official_cache = {}

    parsed_all: list[Parsed] = []
    new_reddit: list[Parsed] = []
    for item in new_items:
        found = parse_item(item, args.model)
        log.info("%s -> %d incident(s)", item.uid, len(found))
        parsed_all.extend(found)
        if item.source == "reddit":
            new_reddit.extend(found)
        else:
            official_cache[item.uid] = official_entries(item, found)
        if writing:
            seen_ids.append(item.uid)

    closures = [p.closure for p in parsed_all]
    if args.dry_run or args.sample:
        print(json.dumps([c.model_dump() for c in closures], indent=2))
    else:
        added = append_closures(args.out, closures)
        _write_json_atomic(SEEN_FILE, seen_ids[-2000:])
        log.info("Wrote %d new closure(s) to %s", added, args.out)

    if args.post_to_backend and not args.dry_run:
        base = args.post_to_backend.rstrip("/")
        sent = post_community(base, new_reddit)
        log.info("Backend: sent %d community report(s) to %s", sent, base)
        if official_complete:
            # Every notice on the page now, including ones parsed on earlier runs
            on_page = [i.uid for i in items if i.source == "official"]
            entries = [e for uid in on_page for e in official_cache.get(uid, [])]
            admin_key = os.environ.get("CAMPUSNAV_ADMIN_KEY", "")
            if not admin_key:
                log.warning("Backend: CAMPUSNAV_ADMIN_KEY not set; skipping the official list")
            elif post_official(base, admin_key, entries):
                log.info("Backend: replaced official list with %d notice(s)", len(entries))
            if not args.sample:
                _write_json_atomic(OFFICIAL_CACHE, {uid: official_cache[uid] for uid in on_page if uid in official_cache})
        else:
            log.info("Backend: facilities page not fetched this run; leaving the official list unchanged")

    return len(closures)


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env")
    except ImportError:
        pass

    p = argparse.ArgumentParser(description="CampusNav Role 3: scrape accessibility incidents into closures.json")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output JSON file (default: closures.json here)")
    p.add_argument("--limit", type=int, default=50, help="how many recent Reddit posts to check")
    p.add_argument("--facilities-url", default=os.environ.get("FACILITIES_URL"), help="facilities alert page to scrape")
    p.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"))
    p.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="repeat every N seconds")
    p.add_argument("--dry-run", action="store_true", help="print results instead of writing files")
    p.add_argument("--sample", action="store_true", help="parse built-in sample posts instead of scraping")
    p.add_argument(
        "--post-to-backend",
        nargs="?",
        const=os.environ.get("CAMPUSNAV_API_URL", "http://127.0.0.1:8000"),
        default=None,
        metavar="URL",
        help="also send results to the CampusNav backend (default URL: CAMPUSNAV_API_URL or http://127.0.0.1:8000)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            raise
        except Exception:  # one bad run must not kill the loop
            log.exception("Run failed; will try again next cycle")
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
