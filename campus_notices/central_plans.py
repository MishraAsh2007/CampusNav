"""Collect the unique plan images embedded on UMass Hospitality's current page."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from .cache import atomic_json

PAGE = "https://umasshospitality.com/locations-capacities"
CONFERENCE_PROGRAM = (
    "https://bpb-us-w2.wpmucdn.com/wordpress.amherst.edu/dist/1/251/"
    "files/2026/03/MAA_2026_Final_Program.pdf"
)
HOTEL_DIRECTIONS = "https://hotelumass.com/faq"
FILES = [
    "first-floor.png",
    "second-floor.jpg",
    "eight-floor.jpg",
    "ten-11-floor.jpg",
    "student-union.jpg",
]


def fetch_images(folder: Path, client=None):
    own = client is None
    client = client or httpx.Client(timeout=35, follow_redirects=False)
    try:
        response = client.get(PAGE)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        urls = {urljoin(PAGE, i["src"]) for i in soup.select("img[src]")}
        rows = []
        for name in FILES:
            url = "https://umasshospitality.com/themes/umass/images/" + name
            if url not in urls:
                raise ValueError("Expected embedded source plan missing")
            response = client.get(url)
            response.raise_for_status()
            if len(response.content) > 10_000_000:
                raise ValueError("Plan image too large")
            pix = pymupdf.Pixmap(response.content)
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            rows.append(
                dict(
                    id=name,
                    url=url,
                    sha256=hashlib.sha256(response.content).hexdigest(),
                    local_path=str(path),
                    width=pix.width,
                    height=pix.height,
                    revision="Not stated by source; current page link is not a revision date",
                )
            )
        atomic_json(
            folder / "image-manifest.json",
            dict(page=PAGE, observed_at=datetime.now(UTC).isoformat(), records=rows),
        )
        return rows
    finally:
        if own:
            client.close()


def collect_sources(folder: Path):
    """Collect public plan references with per-source fallback; never overwrite traces."""
    from scripts.fetch_central_plans import URLS

    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "source-manifest.json"
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    old = {r["id"]: r for r in previous.get("records", [])}
    records, statuses = [], {}
    now = datetime.now(UTC).isoformat()
    try:
        images = fetch_images(folder)
        records.extend(dict(r, observed_at=now) for r in images)
        statuses["hospitality-images"] = dict(mode="live", observed_at=now)
    except Exception as exc:
        records.extend(r for r in old.values() if r["id"] in FILES)
        statuses["hospitality-images"] = dict(
            mode="cache" if records else "unavailable",
            error_type=type(exc).__name__,
            observed_at=previous.get("sources", {})
            .get("hospitality-images", {})
            .get("observed_at"),
        )
    urls = dict(
        URLS,
        **{
            "su-gallery-directions": "https://www.umass.edu/student-life/student-union/art-gallery/accessibility-contact",
            "cc-2026-conference-program": CONFERENCE_PROGRAM,
            "cc-hotel-directions": HOTEL_DIRECTIONS,
        },
    )
    with httpx.Client(timeout=35, follow_redirects=True) as client:
        for key, url in urls.items():
            try:
                response = client.get(url)
                response.raise_for_status()
                if len(response.content) > 20_000_000:
                    raise ValueError("Central plan reference too large")
                if key.endswith("directions"):
                    if key == "su-gallery-directions":
                        from scripts.build_central_wayfinding import student_union

                        student_union(response.text)  # Validate without publishing a graph.
                    else:
                        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
                        if not all(s in text for s in ("concourse", "elevators to the 3rd level")):
                            raise ValueError("Hotel concourse directions changed")
                    suffix, pages = ".html", None
                else:
                    if not response.content.startswith(b"%PDF"):
                        raise ValueError("Reference returned a web page instead of a PDF")
                    with pymupdf.open(stream=response.content, filetype="pdf") as doc:
                        pages = len(doc)
                    suffix = ".pdf"
                path = folder / (key + suffix)
                path.write_bytes(response.content)
                records.append(
                    dict(
                        id=key,
                        url=url,
                        local_path=str(path),
                        pages=pages,
                        sha256=hashlib.sha256(response.content).hexdigest(),
                        observed_at=now,
                    )
                )
                statuses[key] = dict(mode="live", observed_at=now)
            except Exception as exc:
                if key in old:
                    records.append(old[key])
                statuses[key] = dict(
                    mode="cache" if key in old else "unavailable",
                    error_type=type(exc).__name__,
                    observed_at=old.get(key, {}).get("observed_at"),
                )
    payload = dict(observed_at=now, sources=statuses, records=records, routing_eligible=False)
    atomic_json(output, payload)
    return payload
