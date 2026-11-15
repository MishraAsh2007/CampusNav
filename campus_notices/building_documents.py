"""Collect official project documents and Goodell's public directory floor plan."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import pymupdf
from bs4 import BeautifulSoup

from .cache import atomic_json
from .residence_plans import _FreshSharePointClient
from .sharepoint import read_session

PROJECTS = {
    "student-union": "student-union-renovation-2020",
    "honors": "commonwealth-honors-college-2013",
    "campus-center": "lincoln-campus-center-dining-renovations-2014",
    "old-chapel": "old-chapel-renovation-2017",
}
BASE = "https://www.umass.edu/planning-design-construction/book/"
GOODELL_PAGE = (
    "https://www.umass.edu/news/article/goodell-hall-officially-reopens-ribbon-cutting-open-house"
)
GOODELL_IMAGE = (
    "https://www.umass.edu/sites/default/files/2025-04/Goodell%20Floorplan%20March%202025.jpg"
)


def brochure_link(html, label="Green Building Brochure"):
    matches = [
        a["href"]
        for a in BeautifulSoup(html, "html.parser").select("a[href]")
        if a.get_text(" ", strip=True) == label
    ]
    if len(matches) != 1:
        raise ValueError("Official building brochure link changed")
    parsed = urlparse(matches[0])
    if (
        parsed.scheme != "https"
        or parsed.netloc != "umass.sharepoint.com"
        or parsed.username
        or parsed.password
        or not parsed.path.startswith("/:b:/s/AFWD/")
    ):
        raise ValueError("Unexpected building document host or sharing path")
    return matches[0]


def goodell_image(raw):
    """Reject error pages, thumbnails and changed image dimensions before caching."""
    if len(raw) > 20_000_000 or not raw.startswith(b"\xff\xd8"):
        raise ValueError("Goodell source is not a bounded JPEG")
    pix = pymupdf.Pixmap(raw)
    if (pix.width, pix.height) != (5326, 4013):
        raise ValueError("Goodell original image dimensions changed; review source")
    return pix.width, pix.height


def collect(root: Path):
    from playwright.sync_api import sync_playwright

    folder = root / "data/private/building_documents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    old = {r["building_id"]: r for r in previous.get("records", [])}
    now = datetime.now(UTC)
    records, sources = [], {}
    with sync_playwright() as playwright, httpx.Client(timeout=30, follow_redirects=True) as public:
        for key, slug in PROJECTS.items():
            try:
                page = public.get(BASE + slug)
                page.raise_for_status()
                label = "Green Building Tour Guide" if key == "old-chapel" else None
                link = brochure_link(page.text, label or "Green Building Brochure")
                state, agent = read_session(root / "data/private/sharepoint-session.json", now)
                private = _FreshSharePointClient(playwright, state, agent)
                url = link + ("&" if "?" in link else "?") + "download=1"
                response = private.get(url, fail_on_status_code=False, timeout=40000)
                raw = response.body()
                if response.status != 200 or not raw.startswith(b"%PDF"):
                    raise ValueError("Brochure download did not return an accessible PDF")
                if len(raw) > 20_000_000:
                    raise ValueError("Building brochure too large")
                with pymupdf.open(stream=raw, filetype="pdf") as doc:
                    pages = len(doc)
                local = folder / (key + ".pdf")
                local.write_bytes(raw)
                records.append(
                    dict(
                        building_id=key,
                        source_url=link,
                        project_page=BASE + slug,
                        local_path=str(local),
                        pages=pages,
                        sha256=hashlib.sha256(raw).hexdigest(),
                        observed_at=now.isoformat(),
                        routing_eligible=False,
                    )
                )
                sources[key] = dict(mode="live", observed_at=now.isoformat())
            except Exception as exc:
                if key in old:
                    records.append(old[key])
                sources[key] = dict(
                    mode="cache" if key in old else "unavailable",
                    observed_at=old.get(key, {}).get("observed_at"),
                    error_type=type(exc).__name__,
                )
        # Public collection works even when the authenticated session has expired.
        try:
            page = public.get(GOODELL_PAGE)
            page.raise_for_status()
            if unquote(GOODELL_IMAGE).split("/")[-1] not in unquote(page.text):
                raise ValueError("Goodell original image reference missing from official page")
            response = public.get(GOODELL_IMAGE)
            response.raise_for_status()
            width, height = goodell_image(response.content)
            local = folder / "goodell.jpg"
            local.write_bytes(response.content)
            records.append(
                dict(
                    building_id="goodell",
                    source_url=GOODELL_IMAGE,
                    project_page=GOODELL_PAGE,
                    local_path=str(local),
                    width=width,
                    height=height,
                    sha256=hashlib.sha256(response.content).hexdigest(),
                    observed_at=now.isoformat(),
                    routing_eligible=False,
                )
            )
            sources["goodell"] = dict(mode="live", observed_at=now.isoformat())
        except Exception as exc:
            if "goodell" in old:
                records.append(old["goodell"])
            sources["goodell"] = dict(
                mode="cache" if "goodell" in old else "unavailable",
                observed_at=old.get("goodell", {}).get("observed_at"),
                error_type=type(exc).__name__,
            )
    payload = dict(
        observed_at=now.isoformat(),
        records=records,
        sources=sources,
        routing_eligible=False,
        note="Official brochures, Old Chapel tour guide and Goodell directory image. "
        "Source downloads do not automatically publish routing geometry.",
    )
    atomic_json(path, payload)
    return payload
