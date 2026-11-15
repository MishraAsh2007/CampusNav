"""Collect library elevator source evidence without inventing current car topology."""

import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .cache import atomic_json

INDEX = "https://umass.stackmap.com/explore/"
DIRECTORY = "https://people.umass.edu/ref/clipboardmessages/directory.pdf"
LIBRARY = "W. E. B. Du Bois Library"


def floor_references(html):
    """Keep the explicit building/floor identity; never infer it from a filename."""
    result = {}
    for card in BeautifulSoup(html, "html.parser").select(".analytics-card[data-loc]"):
        heading, floor, image = card.find("h1"), card.find("h2"), card.find("img")
        if not heading or heading.get_text(" ", strip=True) != LIBRARY:
            continue
        key = card["data-loc"]
        if not re.fullmatch(r"\d+", key) or not floor or not image or not image.get("src"):
            raise ValueError("Incomplete Du Bois floor reference")
        url = urljoin(INDEX, image["src"])
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "umass.stackmap.com":
            raise ValueError("Unexpected floor image host")
        row = dict(source_floor_id=key, floor_label=floor.get_text(" ", strip=True), image_url=url)
        if key in result and result[key] != row:
            raise ValueError("Conflicting duplicate floor reference")
        result[key] = row
    if not result:
        raise ValueError("No Du Bois floor references; retain previous snapshot")
    return list(result.values())


def elevator_regions(html):
    """StackMap's regions may cover multiple cars. They are not car IDs or doors."""
    soup = BeautifulSoup(html, "html.parser")
    dims = re.search(r"floor_map_dimensions[\"']?\s*:\s*\{([^}]+)\}", html)
    if not dims:
        raise ValueError("Floor map dimensions missing")
    size = {}
    for field in ("width", "height"):
        match = re.search(rf"[\"']{field}[\"']\s*:\s*(\d+)", dims[1])
        if not match or int(match[1]) <= 0:
            raise ValueError("Invalid floor map dimensions")
        size[field] = int(match[1])
    regions, seen = [], set()
    for marker in soup.select(".places-item"):
        if marker.get("aria-label", marker.get("title", "")).strip().casefold() != "elevator":
            continue
        key = marker.get("id")
        if not key or key in seen:
            raise ValueError("Missing or duplicate elevator region ID")
        seen.add(key)
        bounds = {field: float(marker[field]) for field in ("x", "y", "width", "height")}
        if not all(math.isfinite(v) for v in bounds.values()):
            raise ValueError("Non-finite elevator region")
        x, y, w, h = (bounds[k] for k in ("x", "y", "width", "height"))
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > size["width"] or y + h > size["height"]:
            raise ValueError("Elevator region outside floor image")
        regions.append(
            dict(
                source_place_id=key,
                bounds=bounds,
                coordinate_system="image_pixels",
                physical_car_id=None,
                routing_eligible=False,
            )
        )
    return dict(image_dimensions=size, regions=regions)


def historical_service(text):
    """Only recognize the inspected 2007 directory edition, not arbitrary service prose."""
    text = " ".join(text.split())
    required = [
        "7/9/07",
        "Elevators #1 and #2 go to Main, Entrance/Exit, and Express to 16-26",
        "Elevators #3, #4 and #5 go to Main, and Entrance/Exit-16",
    ]
    if not all(phrase in text for phrase in required):
        raise ValueError("Historical elevator directory changed; review before extraction")
    return [
        dict(
            source_car_label=f"#{car}",
            source_edition="2007-07-09",
            source_url=DIRECTORY,
            source_page=2,
            service_description=(
                "Main and entrance/exit levels, then express service to floors 16 through 26."
                if car <= 2
                else "Main and entrance/exit levels through floor 16."
            ),
            current_service_confirmed=False,
            source_floor_labels_preserved=["Main", "Entrance/Exit"],
            plan_region_id=None,
            routing_eligible=False,
        )
        for car in range(1, 6)
    ]


def _read(client, url, limit=5_000_000):
    with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Source redirected; review the destination before collection")
        result = bytearray()
        for chunk in response.iter_bytes():
            result.extend(chunk)
            if len(result) > limit:
                raise ValueError("Library source exceeds size limit")
        return bytes(result)


def collect(output: Path, cache: Path, client=None):
    """Publish only after all discovered floor pages and the directory validate."""
    import pymupdf

    own = client is None
    client = client or httpx.Client(timeout=25)
    cache.mkdir(parents=True, exist_ok=True)
    try:
        index = _read(client, INDEX)
        floors = floor_references(index.decode("utf-8"))
        if output.exists():
            import json

            previous = json.loads(output.read_text(encoding="utf-8"))
            prior_ids = {f["source_floor_id"] for f in previous.get("floors", [])}
            if prior_ids - {f["source_floor_id"] for f in floors}:
                raise ValueError("Previously collected floors disappeared; retain prior snapshot")
        for row in floors:
            url = INDEX + row["source_floor_id"] + "?c=55"
            content = _read(client, url)
            page = content.decode("utf-8")
            # The map's nav state must agree with the requested source floor.
            if not re.search(r'"curFloorId"\s*:\s*"' + row["source_floor_id"] + '"', page):
                raise ValueError("Source returned a different floor")
            row.update(elevator_regions(page))
            row.update(source_url=url, sha256=hashlib.sha256(content).hexdigest())
            (cache / f"floor-{row['source_floor_id']}.html").write_bytes(content)
        if not any(row["regions"] for row in floors):
            raise ValueError("All elevator regions disappeared; retain prior snapshot")
        pdf = _read(client, DIRECTORY)
        if not pdf.startswith(b"%PDF"):
            raise ValueError("Historical directory did not return a PDF")
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            text = " ".join(page.get_text() for page in doc)
        cars = historical_service(text)
        (cache / "directory-2007.pdf").write_bytes(pdf)
        (cache / "index.html").write_bytes(index)
        payload = dict(
            building_id="library",
            observed_at=datetime.now(UTC).isoformat(),
            routing_eligible=False,
            historical_service_applies_to_current_routes=False,
            index_url=INDEX,
            floors=floors,
            missing_directory_floor_labels=(
                [] if any(f["floor_label"] == "3rd Floor" for f in floors) else ["3rd Floor"]
            ),
            historical_cars=cars,
            directory_sha256=hashlib.sha256(pdf).hexdigest(),
            warnings=[
                "Map regions can cover several cars; region counts are not car counts.",
                "Image coordinates are not geographic positions or surveyed doorways.",
                "Historical car numbers are not matched to map regions or current outages.",
                "2007 service patterns must not be promoted to current floor-stop connections.",
            ],
        )
        atomic_json(output, payload)
        return payload
    finally:
        if own:
            client.close()
