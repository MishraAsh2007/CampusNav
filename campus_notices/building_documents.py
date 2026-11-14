"""Collect SharePoint building brochures linked from official UMass project pages."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

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
}
BASE = "https://www.umass.edu/planning-design-construction/book/"


def brochure_link(html):
    matches = [
        a["href"]
        for a in BeautifulSoup(html, "html.parser").select("a[href]")
        if a.get_text(" ", strip=True) == "Green Building Brochure"
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


def collect(root: Path):
    from playwright.sync_api import sync_playwright

    folder = root / "data/private/building_documents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    old = {r["building_id"]: r for r in previous.get("records", [])}
    now = datetime.now(UTC)
    state, agent = read_session(root / "data/private/sharepoint-session.json", now)
    records, sources = [], {}
    with sync_playwright() as playwright, httpx.Client(timeout=30) as public:
        private = _FreshSharePointClient(playwright, state, agent)
        for key, slug in PROJECTS.items():
            try:
                page = public.get(BASE + slug)
                page.raise_for_status()
                link = brochure_link(page.text)
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
    payload = dict(
        observed_at=now.isoformat(),
        records=records,
        sources=sources,
        routing_eligible=False,
        note="Sustainability brochures, not complete indoor navigation plans.",
    )
    atomic_json(path, payload)
    return payload
