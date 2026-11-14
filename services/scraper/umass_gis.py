"""Download and cache UMass building outlines and elevator locations.

Source: the public ArcGIS layers behind the UMass Campus Accessibility Map
(data "as of August 2022"). Each building gets its centroid, a radius that
covers its footprint, and the elevator points that fall inside or within
ELEVATOR_MATCH_M of its outline.

Cached to data/umass_gis.json so parsing works offline after the first run.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

SERVICE = "https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services"
BUILDINGS_LAYER = f"{SERVICE}/BuildingData/FeatureServer/0"
ELEVATORS_LAYER = f"{SERVICE}/Elevators/FeatureServer/0"

DATA_DIR = Path(__file__).resolve().parent / "data"
CACHE_PATH = DATA_DIR / "umass_gis.json"

ELEVATOR_MATCH_M = 8.0
EARTH_R = 6_371_008.8
HEADERS = {"User-Agent": "CampusNav hackathon (UMass accessibility routing)"}


def _query(layer: str, out_fields: str, geometry: bool = True) -> list[dict]:
    feats: list[dict] = []
    offset = 0
    while True:
        r = requests.get(
            f"{layer}/query",
            params={
                "where": "1=1",
                "outFields": out_fields,
                "returnGeometry": "true" if geometry else "false",
                "outSR": 4326,
                "resultOffset": offset,
                "resultRecordCount": 1000,
                "f": "json",
            },
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"ArcGIS error from {layer}: {body['error']}")
        page = body.get("features", [])
        feats.extend(page)
        if not body.get("exceededTransferLimit") or not page:
            return feats
        offset += len(page)


# ---------------------------------------------------------------- geometry
def _xy(lat0: float, lon: float, lat: float, lon0: float) -> tuple[float, float]:
    """Local equirectangular projection in meters around (lat0, lon0)."""
    k = math.pi / 180 * EARTH_R
    return (lon - lon0) * k * math.cos(math.radians(lat0)), (lat - lat0) * k


def _point_in_rings(x: float, y: float, rings: list[list[tuple[float, float]]]) -> bool:
    """Even-odd rule over all rings (holes handled naturally)."""
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def _dist_to_rings(x: float, y: float, rings: list[list[tuple[float, float]]]) -> float:
    best = math.inf
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            dx, dy = x2 - x1, y2 - y1
            t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def build_cache() -> dict:
    buildings_raw = _query(BUILDINGS_LAYER, "BuildingName,BuildingID,AccessLevel")
    elevators_raw = _query(ELEVATORS_LAYER, "OBJECTID")

    buildings = []
    for f in buildings_raw:
        a, g = f["attributes"], f.get("geometry") or {}
        rings_ll = g.get("rings") or []
        name = (a.get("BuildingName") or "").strip()
        if not name or not rings_ll:
            continue
        pts = [p for ring in rings_ll for p in ring]
        lon0 = sum(p[0] for p in pts) / len(pts)
        lat0 = sum(p[1] for p in pts) / len(pts)
        rings = [[_xy(lat0, lon, lat, lon0) for lon, lat in ring] for ring in rings_ll]
        radius = max(math.hypot(x, y) for ring in rings for x, y in ring)

        elevators = []
        for e in elevators_raw:
            elat, elon = e["geometry"]["y"], e["geometry"]["x"]
            ex, ey = _xy(lat0, elon, elat, lon0)
            if math.hypot(ex, ey) > radius + ELEVATOR_MATCH_M:
                continue
            if _point_in_rings(ex, ey, rings) or _dist_to_rings(ex, ey, rings) <= ELEVATOR_MATCH_M:
                elevators.append({"id": int(e["attributes"]["OBJECTID"]), "lat": round(elat, 7), "lon": round(elon, 7)})

        buildings.append(
            {
                "name": name,
                "id": a.get("BuildingID"),
                "access_level": a.get("AccessLevel"),
                "centroid": [round(lat0, 7), round(lon0, 7)],
                "radius_m": round(radius, 1),
                "elevators": elevators,
            }
        )

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "UMass Campus Accessibility Map ArcGIS layers (data as of August 2022)",
        "buildings": sorted(buildings, key=lambda b: b["name"]),
    }


def write_json_atomic(path: Path, data) -> None:
    """Write via a temp file + rename so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_gis(refresh: bool = False, path: Path = CACHE_PATH) -> dict:
    """Cached GIS data; downloads on first use or when refresh=True."""
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = build_cache()
    write_json_atomic(path, data)
    return data


if __name__ == "__main__":
    d = load_gis(refresh=True)
    n_el = sum(len(b["elevators"]) for b in d["buildings"])
    print(f"cached {len(d['buildings'])} buildings, {n_el} elevators -> {CACHE_PATH}")
