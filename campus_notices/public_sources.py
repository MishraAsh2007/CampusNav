"""Bounded, read-only public feeds and authorized social APIs. No browser login scraping."""

import hashlib
import ipaddress
import json
import os
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

import httpx
from pydantic import AwareDatetime, Field

from campus_routing.models import ContractModel

from .sources import SourceError, clean_text

MAX_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 200
USER_AGENT = "CampusNavigation/0.1 (UMass campus accessibility reports)"
PVTA_URL = "https://pvta.us/swiftly/RevizeAlerts2.php"
UMASS_ROUTES = {
    "30",
    "31",
    "33",
    "34",
    "35",
    "36",
    "38",
    "38NS",
    "45",
    "46",
    "B43",
    "B43E",
    "B79",
    "UMG",
}


class NotConfigured(SourceError):
    pass


class PublicPost(ContractModel):
    native_id: str
    url: str
    title: str = Field(max_length=500)
    text: str = Field(max_length=6000)
    published_at: AwareDatetime | None = None


def public_url(value, *, base=""):
    url = urljoin(base, value)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or host in ("localhost", "localhost.localdomain")
        or host.endswith((".localhost", ".local"))
    ):
        raise SourceError("Public sources require an HTTPS URL without embedded credentials")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise SourceError("Public source URLs cannot point to a private network address")
    return urlunparse(parsed._replace(fragment=""))


def timestamp(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            return None
    return result.astimezone(UTC) if result.tzinfo else None


def post(ident, url, title, text, published=None):
    # Author profiles and contact columns are never retained. Strip handles from text too.
    def scrub(value):
        return re.sub(r"(?<!\w)(?:/u/|u/|@)[\w-]+", "[handle removed]", clean_text(value))

    return PublicPost(
        native_id=str(ident),
        url=public_url(url),
        title=scrub(title)[:500],
        text=scrub(text)[:6000],
        published_at=timestamp(published),
    )


def download(client, url, *, headers=None, params=None):
    url = public_url(url)
    try:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            params=params,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise SourceError("Source redirected; configure its final public URL")
            if response.status_code in (401, 403):
                raise SourceError(f"Source access denied (HTTP {response.status_code})")
            if response.status_code == 429:
                raise SourceError("Source rate limited this refresh (HTTP 429); try later")
            if response.status_code != 200:
                raise SourceError(f"Source returned HTTP {response.status_code}")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise SourceError("Public source exceeds 5 MB")
            return bytes(content)
    except httpx.HTTPError as exc:
        raise SourceError(f"Source connection failed ({type(exc).__name__})") from None


def read_feed(data, source_url):
    if b"<!doctype" in data.lower() or b"<!entity" in data.lower():
        raise SourceError("Feed document declarations are not supported")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise SourceError("Expected an RSS/Atom feed, not a login or error page") from None
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise SourceError("RSS channel is missing")
        entries = channel.findall("item")
        atom = False
    elif root.tag == "{http://www.w3.org/2005/Atom}feed":
        entries = root.findall("atom:entry", ns)
        atom = True
    else:
        raise SourceError("Unsupported feed format")
    output = []
    for entry in entries[:MAX_ITEMS]:
        if atom:
            links = entry.findall("atom:link", ns)
            link = next(
                (e.get("href") for e in links if e.get("rel", "alternate") == "alternate"), None
            )
            title = entry.findtext("atom:title", "", ns)
            text = entry.findtext("atom:content", None, ns) or entry.findtext(
                "atom:summary", "", ns
            )
            ident = entry.findtext("atom:id", link, ns)
            published = entry.findtext("atom:published", None, ns)
        else:
            link, title = entry.findtext("link"), entry.findtext("title", "")
            text = entry.findtext("description", "")
            ident = entry.findtext("guid", link)
            published = entry.findtext("pubDate")
        if not link:
            raise SourceError("Feed entry is missing its source link")
        output.append(
            post(ident or link, public_url(link, base=source_url), title, text, published)
        )
    return output


def read_html(data, spec):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    if soup.select_one('input[type="password"]'):
        raise SourceError("Public page requires sign-in")
    selector = spec.get("item_selector")
    if not selector:
        raise NotConfigured("Set item_selector for this public page's individual reports")
    items = soup.select(selector)
    if not items:
        empty = spec.get("empty_selector")
        if empty and soup.select_one(empty):
            return []
        raise SourceError("No matching report elements; the page structure may have changed")
    output = []
    for item in items[:MAX_ITEMS]:
        heading = item.select_one(spec.get("title_selector", "h1,h2,h3"))
        content = item.select_one(spec.get("text_selector", ".description,.summary")) or item
        link = item.select_one(spec.get("link_selector", "a[href]"))
        clock = item.select_one(spec.get("time_selector", "time[datetime]"))
        if not link:
            raise SourceError("A public report is missing its permalink")
        url = public_url(link.get("href", ""), base=spec["url"])
        output.append(
            post(
                url,
                url,
                heading.get_text(" ", strip=True) if heading else "Report",
                content.get_text(" ", strip=True),
                clock.get("datetime") if clock else None,
            )
        )
    return output


def read_pvta(data, routes):
    """Read the actual alert embed linked by PVTA's Service Alerts & Detours page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup.select("script,style,nav,header,footer"):
        tag.decompose()
    lines = [s.strip() for s in soup.get_text("\n", strip=True).splitlines() if s.strip()]
    effects = [i for i, line in enumerate(lines) if re.match(r"^Effect:\s*\S", line)]
    if not effects:
        if re.search(
            r"\bno (?:active |current )?(?:alerts|service alerts)\b", " ".join(lines), re.I
        ):
            return []
        raise SourceError("PVTA alert elements were not found; refusing an empty success")
    starts = []
    route_line = re.compile(r"^(?:[A-Z]*\d+(?:NS|E)?|UMG)(?:\s+(?:[A-Z]*\d+(?:NS|E)?|UMG))*$")
    for index in effects:
        start = max(0, index - 1)  # title immediately precedes Effect
        while start > 0 and route_line.fullmatch(lines[start - 1]):
            start -= 1
        starts.append(start)
    posts = []
    for number, index in enumerate(effects):
        end = starts[number + 1] if number + 1 < len(starts) else len(lines)
        title = lines[index - 1] if index else "PVTA service alert"
        context = " ".join(lines[starts[number] : end])
        # Match route badges, not incidental dates, street numbers, or durations.
        mentioned = set(" ".join(lines[starts[number] : max(0, index - 1)]).split())
        if routes and not mentioned.intersection(routes):
            continue
        ident = hashlib.sha256(context.encode()).hexdigest()[:24]
        # The current embed gives no machine-readable publication timestamps.
        posts.append(post(ident, PVTA_URL, title, context))
    return posts[:MAX_ITEMS]


def read_reddit(client, spec):
    token = os.getenv(spec.get("token_env", "REDDIT_ACCESS_TOKEN"))
    agent = os.getenv("REDDIT_USER_AGENT")
    if not token or not agent:
        raise NotConfigured(
            "Reddit needs an approved app's REDDIT_ACCESS_TOKEN and REDDIT_USER_AGENT"
        )
    subreddit = spec.get("subreddit", "umass")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,40}", subreddit):
        raise SourceError("Invalid subreddit name")
    output = []
    for listing in ("new", "comments") if spec.get("include_comments", True) else ("new",):
        payload = json.loads(
            download(
                client,
                f"https://oauth.reddit.com/r/{subreddit}/{listing}",
                headers={"Authorization": f"Bearer {token}", "User-Agent": agent},
                params={"limit": 100, "raw_json": 1},
            )
        )
        if payload.get("kind") != "Listing" or not isinstance(
            payload.get("data", {}).get("children"), list
        ):
            raise SourceError("Reddit did not return a valid listing")
        for row in payload["data"]["children"][:100]:
            item = row.get("data", {})
            body = item.get("selftext", item.get("body", ""))
            if body in ("[deleted]", "[removed]") or item.get("removed_by_category"):
                continue
            ident, link = item.get("name"), item.get("permalink")
            if not ident or not link:
                raise SourceError("Reddit item is missing its ID or permalink")
            url = public_url(link, base="https://www.reddit.com")
            if urlparse(url).hostname != "www.reddit.com":
                raise SourceError("Unexpected Reddit permalink host")
            output.append(
                post(ident, url, item.get("title", "Reddit comment"), body, item.get("created_utc"))
            )
    return output


def read_facebook(client, spec):
    token = os.getenv(spec.get("token_env", "FACEBOOK_PAGE_ACCESS_TOKEN"))
    page_id = spec.get("page_id", "")
    if not token or not re.fullmatch(r"\d+", page_id):
        raise NotConfigured("Facebook needs a Page ID and authorized FACEBOOK_PAGE_ACCESS_TOKEN")
    version = spec.get("api_version", "v27.0")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise SourceError("Invalid Facebook API version")
    payload = json.loads(
        download(
            client,
            f"https://graph.facebook.com/{version}/{page_id}/feed",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "id,message,created_time,permalink_url", "limit": 100},
        )
    )
    if not isinstance(payload.get("data"), list) or "error" in payload:
        raise SourceError("Facebook did not return an authorized Page feed")
    posts = []
    for item in payload["data"][:100]:
        if not item.get("message"):
            continue
        if not item.get("id") or not item.get("permalink_url"):
            raise SourceError("Facebook post is missing its ID or permalink")
        url = public_url(item["permalink_url"])
        if urlparse(url).hostname not in ("www.facebook.com", "facebook.com"):
            raise SourceError("Unexpected Facebook permalink host")
        posts.append(
            post(item["id"], url, "Facebook Page post", item["message"], item.get("created_time"))
        )
    return posts


def fetch_posts(spec, *, client):
    kind = spec["kind"]
    if kind == "reddit":
        return read_reddit(client, spec)
    if kind == "facebook":
        return read_facebook(client, spec)
    data = download(client, spec["url"])
    if kind == "rss":
        return read_feed(data, spec["url"])
    if kind == "html":
        return read_html(data, spec)
    if kind == "pvta":
        return read_pvta(data, set(spec.get("routes", UMASS_ROUTES)))
    raise SourceError(f"Unsupported public source kind: {kind}")
