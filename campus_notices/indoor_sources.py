"""Scrape public floor directories and floor-plan references, not imagined corridors."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .cache import atomic_json, writer_lock
from .indoor_arcgis import GIS_SOURCES, fetch_references

SOURCES = {
    "library-directory": "https://www.library.umass.edu/du-bois-library/",
    "library-floorplans": "https://umass.stackmap.com/explore/",
    "campus-center-directory": "https://www.umass.edu/af/space-use/campus-center",
    "ilc-classrooms": "https://www.umass.edu/registrar/room-types-and-capacities-ilc",
    **{key: value["url"] for key, value in GIS_SOURCES.items()},
}


def ident(*parts):
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def parse_source(key, html, observed_at):
    soup = BeautifulSoup(html, "html.parser")
    url = SOURCES[key]
    rows = []

    def record(building, floor_label, label, kind, **extras):
        return dict(
            id=ident(key, building, floor_label or "", label),
            building_id=building,
            floor_label=floor_label,
            label=label,
            kind=kind,
            source_id=key,
            source_url=url,
            observed_at=observed_at.isoformat(),
            routing_eligible=False,
            review_status="needs_topology_review",
            **extras,
        )

    if key == "library-floorplans":
        for card in soup.select(".analytics-card"):
            h1, h2, image = card.find("h1"), card.find("h2"), card.find("img")
            if not h1 or "Du Bois" not in h1.get_text() or not h2 or not image:
                continue
            floor = h2.get_text(" ", strip=True)
            image_url = urljoin(url, image.get("src", ""))
            parsed = urlparse(image_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "umass.stackmap.com"
                or not parsed.path.startswith("/media/maps/")
            ):
                raise ValueError("Unexpected floor-plan image source")
            rows.append(
                record(
                    "library",
                    floor,
                    f"Library {floor} plan",
                    "floor_plan",
                    image_url=image_url,
                    coordinate_system="image_pixels",
                    edition="Not stated by source",
                    source_locator=f"data-loc={card.get('data-loc')}",
                    review_notes="Verify scale, corridors, elevator stops, "
                    "and floor-label aliases before routing.",
                )
            )
    elif key == "library-directory":
        for table in soup.select("table"):
            headers = [h.get_text(" ", strip=True).casefold() for h in table.select("th")]
            if not {"floor", "services", "features"}.issubset(headers):
                continue
            for row in table.select("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
                if len(cells) != 3:
                    continue
                floor, services, features = cells
                if not re.fullmatch(r"(?:\d{1,2}|E|LL)", floor):
                    raise ValueError("Unrecognized library floor label; preserve prior data")
                rows.append(
                    record(
                        "library",
                        floor,
                        services,
                        "floor_directory",
                        features=features,
                        evidence=" | ".join(cells),
                        review_notes="Floor/service association only; "
                        "no room coordinates or corridors supplied.",
                    )
                )
    elif key == "campus-center-directory":
        for table in soup.select("table"):
            if "Floor Plans & Capacity Chart" not in table.get_text(" ", strip=True):
                continue
            for row in table.select("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
                if len(cells) < 2:
                    continue
                room, location = cells[:2]
                match = re.fullmatch(r"(\d+)(?:st|nd|rd|th) Floor Campus Center", location, re.I)
                if match:
                    rows.append(
                        record(
                            "campus-center",
                            match[1],
                            room,
                            "room_directory",
                            evidence=f"{room} | {location}",
                            review_notes="Explicit source floor; never inferred from room number. "
                            "Position unknown.",
                        )
                    )
    elif key == "ilc-classrooms":
        for table in soup.select("table"):
            headers = {h.get_text(" ", strip=True).casefold() for h in table.select("th")}
            if not {"room", "capacity", "type of room", "room details"}.issubset(headers):
                continue
            for row in table.select("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
                if len(cells) != 4:
                    continue
                room, capacity, room_type, details = cells
                if not re.fullmatch(r"[NS]\d{3}", room) or not capacity.isdigit():
                    raise ValueError("Unexpected ILC room layout; preserve prior data")
                # N151 explicitly has two entry floors. Never infer a room's floor
                # from its first digit: that would lose multi-level rooms and doorways.
                entry_floors = (
                    ["1", "2"]
                    if re.search(r"entryway from 1st and 2nd floors", details, re.I)
                    else []
                )
                rows.append(
                    record(
                        "ilc",
                        None,
                        room,
                        "room_directory",
                        room_id=room,
                        room_type=room_type,
                        capacity=int(capacity),
                        floor_labels=entry_floors,
                        evidence=" | ".join(cells),
                        review_notes="Room identity only. Entry floors are recorded only when "
                        "explicit in the source; doorway geometry and access are unknown.",
                    )
                )
    else:
        raise ValueError("Unknown indoor source")
    unique = {}
    for row in rows:
        if row["id"] in unique and unique[row["id"]] != row:
            raise ValueError("Conflicting duplicate floor records")
        unique[row["id"]] = row
    rows = list(unique.values())
    if not rows or len(rows) > 1000:
        raise ValueError("Source layout changed or returned no unique floor records")
    return rows


def download(client, url):
    with client.stream(
        "GET",
        url,
        follow_redirects=False,
        headers={"User-Agent": "CampusNav/0.1 public indoor-source import"},
    ) as response:
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            raise ValueError("Expected public HTML")
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > 5 * 1024 * 1024:
                raise ValueError("Indoor source exceeds size limit")
    return content.decode("utf-8")


def refresh_indoor_sources(output: Path, *, client=None, now=None):
    now = now or datetime.now(UTC)
    with writer_lock(output):
        previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        own_client = client is None
        client = client or httpx.Client(timeout=35)
        records, statuses = [], {}
        try:
            for key, url in SOURCES.items():
                try:
                    batch = (
                        fetch_references(key, client, now)
                        if key in GIS_SOURCES
                        else parse_source(key, download(client, url), now)
                    )
                    statuses[key] = dict(
                        mode="live",
                        observed_at=now.isoformat(),
                        attempted_at=now.isoformat(),
                        count=len(batch),
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    batch = [r for r in previous.get("records", []) if r["source_id"] == key]
                    old = previous.get("sources", {}).get(key, {})
                    statuses[key] = dict(
                        mode="cache" if batch else "unavailable",
                        observed_at=old.get("observed_at"),
                        attempted_at=now.isoformat(),
                        count=len(batch),
                        error_type=type(exc).__name__,
                    )
                records.extend(batch)
        finally:
            if own_client:
                client.close()
        payload = dict(
            version=1,
            generated_at=now.isoformat(),
            sources=statuses,
            records=records,
            routing_eligible=False,
            note="Source references only. Reviewed topology is published separately "
            "under data/indoor/.",
        )
        atomic_json(output, payload)
        return payload


def create_indoor_drafts(payload, folder: Path):
    """Expose actual floor images for Role 2 without claiming a routable campus map.

    Existing drafts and reviewed maps are never overwritten by a scrape.
    """
    from campus_routing.indoor import IndoorMap

    created = []
    for building_id, name, kind in (
        ("library", "W. E. B. Du Bois Library", "floor_plan"),
        ("campus-center", "Lincoln Campus Center", "room_directory"),
        ("ilc", "Integrative Learning Center", "room_directory"),
    ):
        path = folder / (building_id + ".json")
        rows = [
            r
            for r in payload["records"]
            if r["building_id"] == building_id and (r["kind"] == kind or building_id == "ilc")
        ]
        if path.exists() or not rows:
            continue
        floors = {}
        for row in rows:
            labels = [row["floor_label"]] if row["floor_label"] else row.get("floor_labels", [])
            for label in labels:
                floor_id = (
                    str(int(label))
                    if label.isdigit()
                    else (re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"))
                )
                floors.setdefault(
                    floor_id,
                    dict(
                        id=floor_id,
                        label=label,
                        source_id=row["source_id"],
                        coordinate_system="image_pixels"
                        if kind == "floor_plan"
                        else "local_meters",
                        image_url=row.get("image_url"),
                    ),
                )
        if not floors:
            continue
        draft = IndoorMap.model_validate(
            dict(
                building_id=building_id,
                name=name,
                status="draft",
                floors=list(floors.values()),
                review_notes="Scraped floor references only. "
                "No corridor, stop or portal geometry inferred.",
                sources=[
                    dict(
                        id=sid,
                        url=SOURCES[sid],
                        edition="Not stated by source",
                        observed_at=next(r["observed_at"] for r in rows if r["source_id"] == sid),
                    )
                    for sid in dict.fromkeys(r["source_id"] for r in rows)
                ],
            )
        )
        atomic_json(path, draft.model_dump(mode="json"))
        created.append(path)
    return created
