"""Fetch the public UMass accessibility map and combine its positions with cached OSM entrances."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pyproj import Transformer
from shapely import transform
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from campus_notices.cache import atomic_json

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services"
MAP_URL = (
    "https://www.arcgis.com/apps/instant/basic/index.html?appid=4575634567794afd863c83bc4d6d6d4a"
)
SOURCES = {
    "buildings": ("BuildingData", "OBJECTID,BuildingID,BuildingName,AccessLevel"),
    "entrances": (
        "Entrances",
        "OBJECTID,IsKeyCardRequired,hasAutoDoorOpener,isAccessibleToAllFloors",
    ),
    "elevators": ("Elevators", "OBJECTID,Description"),
}
BUILDINGS = {
    "080": ("old-chapel", "Old Chapel", "CHAP", "student_services", ["Old Chapel", "Chapel"]),
    "413": (
        "campus-center",
        "Lincoln Campus Center",
        "CC",
        "student_services",
        ["Campus Center", "Lincoln Campus Center"],
    ),
    "704": (
        "ilc",
        "Integrative Learning Center",
        "ILC",
        "academic",
        ["ILC", "Integrative Learning Center"],
    ),
    "131": ("student-union", "Student Union", "SU", "student_services", ["Student Union"]),
    "417": (
        "library",
        "W.E.B. Du Bois Library",
        "LIB",
        "library",
        ["DuBois", "Du Bois", "Library"],
    ),
    "171": ("goodell", "Goodell Hall", "GDL", "administration", ["Goodell"]),
    "378": ("patterson", "Patterson House", "PAT", "residential", ["Patterson"]),
    "330": ("grayson", "Grayson House", "GRY", "residential", ["Grayson"]),
}
EXTRA_PARTS = {"172": "171"}
PROJECT = Transformer.from_crs(4326, 32618, always_xy=True).transform
WEST, SOUTH, EAST, NORTH = (-72.536, 42.3835, -72.519, 42.3955)


def fetch_layer(client, name, fields, *, object_id_field="OBJECTID"):
    url = f"{SERVICE}/{name}/FeatureServer/0/query"
    rows, ids = [], set()
    for offset in range(0, 10000, 1000):
        response = client.get(
            url,
            params={
                "f": "json",
                "where": "1=1",
                "outFields": fields,
                "outSR": "4326",
                "returnGeometry": "true",
                "orderByFields": object_id_field,
                "resultRecordCount": 1000,
                "resultOffset": offset,
            },
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data or not isinstance(data.get("features"), list):
            raise ValueError("The public map did not return a complete feature page")
        for row in data["features"]:
            oid = row["attributes"][object_id_field]
            if oid in ids:
                raise ValueError("Repeated source feature; refusing partial data")
            ids.add(oid)
            rows.append(row)
        if not data.get("exceededTransferLimit"):
            return rows
    raise ValueError("Public map pagination limit exceeded")


def point(row):
    g = row["geometry"]
    return Point(g["x"], g["y"])


def covered(p):
    return WEST <= p.x <= EAST and SOUTH <= p.y <= NORTH


def normalize(data, osm, now, *, building_specs=None, bbox=None):
    specs = BUILDINGS if building_specs is None else building_specs
    west, south, east, north = bbox or (WEST, SOUTH, EAST, NORTH)

    def in_area(p):
        return west <= p.x <= east and south <= p.y <= north

    footprints, records = {}, {}
    for row in data["buildings"]:
        key = str(row["attributes"]["BuildingID"])
        group = EXTRA_PARTS.get(key, key)
        if group not in specs:
            continue
        poly = unary_union([Polygon(r).buffer(0) for r in row["geometry"]["rings"]])
        footprints[group] = unary_union([footprints.get(group, poly), poly])
        if key == group:
            records[group] = row["attributes"]
    metric = {key: transform(p, PROJECT, interleaved=False) for key, p in footprints.items()}
    buildings, assets = [], []
    for key, (ident, name, code, category, aliases) in specs.items():
        if key not in records:
            raise ValueError(f"Source building missing: {name}")
        poly, attrs = footprints[key], records[key]
        center = poly.centroid
        entrances, lifts = [], []

        def belongs(p, limit, building_key=key):
            # Ambiguous entrances shared by adjacent footprints are left unassigned.
            distances = sorted(
                (shape.distance(transform(p, PROJECT, interleaved=False)), k)
                for k, shape in metric.items()
            )
            return (
                distances[0][1] == building_key
                and distances[0][0] <= limit
                and (len(distances) < 2 or distances[1][0] - distances[0][0] > 2)
            )

        def label(p, building_center=center):
            dx, dy = PROJECT(p.x, p.y)
            cx, cy = PROJECT(building_center.x, building_center.y)
            return ("North" if dy > cy else "South") + ("east" if dx > cx else "west") + " entrance"

        for row in data["entrances"]:
            p, a = point(row), row["attributes"]
            if not belongs(p, 10):
                continue
            eid = f"umass-entrance-{a['OBJECTID']}"
            entrances.append(
                {
                    "id": eid,
                    "name": label(p),
                    "lat": p.y,
                    "lng": p.x,
                    "step_free": True if a.get("isAccessibleToAllFloors") == 1 else None,
                    "door_type": "push-button"
                    if a.get("hasAutoDoorOpener") == 1
                    else "manual"
                    if a.get("hasAutoDoorOpener") == 0
                    else "unknown",
                    "keycard_required": a.get("IsKeyCardRequired") == 1,
                    "has_ramp": None,
                    "source": "UMass accessibility map (August 2022)",
                    "source_url": f"{SERVICE}/Entrances/FeatureServer/0/{a['OBJECTID']}",
                    "notes": "All floors accessible in the source map."
                    if a.get("isAccessibleToAllFloors") == 1
                    else (
                        "Source says not all floors are accessible; "
                        "step-free access to this door is unverified."
                    ),
                    "in_routing_area": in_area(p),
                }
            )
        for row in osm.get("elements", []):
            tags = row.get("tags", {})
            if row["type"] != "node" or tags.get("entrance") not in ("yes", "main"):
                continue
            p = Point(row["lon"], row["lat"])
            if not belongs(p, 3):
                continue
            nearby = [
                e
                for e in entrances
                if Point(PROJECT(e["lng"], e["lat"])).distance(Point(PROJECT(p.x, p.y))) < 8
            ]
            if nearby:
                # Nearby points might be different doors. Keep their evidence and flag
                # conflicting access instead of promoting an uncertain point to accessible.
                for entrance in nearby:
                    entrance.setdefault("supplemental_sources", []).append(
                        f"https://www.openstreetmap.org/node/{row['id']}"
                    )
                    if tags.get("wheelchair") == "no":
                        entrance["step_free"] = False
                        entrance["notes"] += (
                            " Nearby OSM data marks wheelchair access as unavailable; "
                            "excluded from step-free entrance choices pending review."
                        )
                    if tags.get("access") in ("private", "no"):
                        entrance["keycard_required"] = True
                continue
            entrances.append(
                {
                    "id": f"osm-entrance-{row['id']}",
                    "name": label(p),
                    "lat": p.y,
                    "lng": p.x,
                    "step_free": {"yes": True, "no": False}.get(tags.get("wheelchair")),
                    "door_type": "unknown",
                    "keycard_required": tags.get("access") in ("private", "no"),
                    "has_ramp": None,
                    "level": tags.get("level"),
                    "osm_id": row["id"],
                    "source": "OpenStreetMap",
                    "source_url": f"https://www.openstreetmap.org/node/{row['id']}",
                    "notes": (
                        "Entrance position from OpenStreetMap; "
                        "door access and operation have not been field verified."
                    ),
                    "in_routing_area": in_area(p),
                }
            )
        for row in data["elevators"]:
            p, a = point(row), row["attributes"]
            if not belongs(p, 1):
                continue
            eid = f"umass-elevator-{a['OBJECTID']}"
            lifts.append(
                {
                    "id": eid,
                    "name": "Mapped elevator location",
                    "lat": p.y,
                    "lng": p.x,
                    "floors": "Floors not specified",
                    "status": "unknown",
                    "connector_id": eid,
                }
            )
            assets.append(
                {
                    "id": eid,
                    "name": f"{name} mapped elevator location",
                    "type": "elevator",
                    "lat": p.y,
                    "lng": p.x,
                    "radius": 4,
                    "building_aliases": aliases,
                    "asset_phrases": ["elevator"],
                    "reviewed": True,
                    "synthetic": False,
                    "evidence": (
                        f"{SERVICE}/Elevators/FeatureServer/0/{a['OBJECTID']}; "
                        f"point lies in {name}'s official footprint. Map edition August 2022. "
                        "A map point may represent an elevator bank; "
                        "no indoor graph connection inferred."
                    ),
                }
            )
        kinds = {e["door_type"] for e in entrances if e["step_free"] is True}
        buildings.append(
            {
                "id": ident,
                "name": name,
                "code": code,
                "category": category,
                "location": {"lat": center.y, "lng": center.x},
                "entrances": entrances,
                "step_free_entrances": [e for e in entrances if e["step_free"] is True],
                "door_type": next(iter(kinds))
                if len(kinds) == 1
                else "mixed"
                if kinds
                else "unknown",
                "elevators": {
                    "total_count": None,
                    "working_count": None,
                    "mapped_locations": len(lifts),
                    "floors_served": "Not specified by source",
                    "status": "unknown",
                    "list": lifts,
                },
                "accessible_restrooms": None,
                "all_floors_accessible": attrs.get("AccessLevel")
                in ("Fully Accessible", "All Floors Accessible (not all doors and toilets)"),
                "access_level": attrs.get("AccessLevel"),
                "source_url": MAP_URL,
                "source_as_of": "August 2022",
                "in_routing_area": in_area(center),
                "notes": (
                    "UMass accessibility map with supplemental OSM entrance positions. "
                    "Routing covers outdoor paths; indoor elevator travel is not modeled."
                ),
            }
        )
    return {
        "generated_at": now.isoformat(),
        "source_url": MAP_URL,
        "source_as_of": "August 2022",
        "buildings": buildings,
    }, assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm-cache", type=Path)
    parser.add_argument("--gis-cache", type=Path, help="Reuse this run's public GIS collection")
    parser.add_argument("--allow-no-osm", action="store_true")
    args = parser.parse_args()
    osm_path = args.osm_cache or next((ROOT / ".cache/osm").glob("*.json"), None)
    if not osm_path and not args.allow_no_osm:
        parser.error("Build the campus graph first to populate the OSM cache")
    if args.gis_cache:
        data = json.loads(args.gis_cache.read_text(encoding="utf-8"))
    else:
        with httpx.Client(timeout=40, follow_redirects=False) as client:
            data = {key: fetch_layer(client, *spec) for key, spec in SOURCES.items()}
    catalog, assets = normalize(
        data,
        json.loads(osm_path.read_text(encoding="utf-8")) if osm_path else {"elements": []},
        datetime.now(UTC),
    )
    atomic_json(ROOT / "data/buildings.json", catalog)
    # Keep manually reviewed assets. Only update this importer's own IDs.
    registry_path = ROOT / "data/location_registry.json"
    old = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    atomic_json(
        registry_path, [a for a in old if not a["id"].startswith("umass-elevator-")] + assets
    )
    entrance_count = sum(len(b["entrances"]) for b in catalog["buildings"])
    print(
        f"Saved {len(catalog['buildings'])} buildings and {entrance_count} entrances; "
        f"{len(assets)} mapped elevator locations."
    )
    for building in catalog["buildings"]:
        print(
            f"{building['name']}: {len(building['entrances'])} entrances; "
            f"routing area={building['in_routing_area']}"
        )


if __name__ == "__main__":
    main()
