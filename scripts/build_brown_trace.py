"""Build a source-backed Brown House indoor draft from the official plan PDFs."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

from campus_notices.cache import atomic_json

ROOT = Path(__file__).resolve().parents[1]
BUILDING = "brown-house"
FLOOR_ORDER = ["basement", "1", "2", "3", "4", "5", "6", "7", "8"]
SPINE_X = (90.0, 220.0, 370.0, 520.0, 705.0)
SPINE_Y = 330.0
ROOM_TOKEN = re.compile(r"^(?:-\d{2}[A-Z]?|\d{3}[A-Z]?)$")


def _source_url(relative):
    return (
        "https://umass.sharepoint.com/sites/SACLCommunications"
        + "/_api/web/GetFileByServerRelativeUrl(@p)/$value?@p="
        + quote("'" + relative + "'", safe="")
    )


def _floor_label(value):
    return "Ground / basement" if value == "basement" else f"Floor {value}"


def _room_label(token, floor):
    if token.startswith("-"):
        return f"{floor}{token[1:]}"
    return token


def _source_for_floor(records, floor):
    if floor == "basement":
        return next(row for row in records if row["name"] == "426-BT.pdf")
    if floor == "1":
        return next(row for row in records if row["name"] == "426-01.pdf")
    return next(row for row in records if row["name"].startswith("426-02.03.04.05.06.07.08"))


def _candidate_rooms(record, floor):
    result = []
    for candidate in record["trace"]["room_label_candidates"]:
        token = candidate["label"]
        if not ROOM_TOKEN.fullmatch(token):
            continue
        if floor == "basement" and token.startswith("-"):
            continue
        if floor == "1" and not token.startswith("1"):
            continue
        if floor not in ("basement", "1") and not token.startswith("-"):
            continue
        label = _room_label(token, floor if floor not in ("basement", "1") else "")
        if label in {row["label"] for row in result}:
            continue
        result.append({"label": label, "x": candidate["x"], "y": candidate["y"]})
    return result


def build_unverified_projection(manifest_path: Path, output: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = [
        row
        for row in manifest["records"]
        if row["area"] == "Sylvan" and row["building"] == "Brown Hall"
    ]
    if len(records) != 3:
        raise ValueError("Expected Brown House's three official plan PDFs")

    sources = []
    source_ids = {}
    for record in records:
        source_id = "brown-house-" + Path(record["name"]).stem.lower().replace(".", "-")
        source_ids[record["name"]] = source_id
        sources.append(
            {
                "id": source_id,
                "url": _source_url(record["server_relative_url"]),
                "edition": f"UMass Residential Life {record['name']}",
                "observed_at": record["modified"] or manifest["observed_at"],
            }
        )
    accessibility_source_id = "brown-house-accessibility-map"
    sources.append(
        {
            "id": accessibility_source_id,
            "url": (
                "https://www.arcgis.com/apps/instant/basic/index.html"
                "?appid=4575634567794afd863c83bc4d6d6d4a"
            ),
            "edition": (
                "UMass accessibility map (source as of August 2022); "
                "Brown House entrance OBJECTID 3 and elevator OBJECTID 186"
            ),
            "observed_at": manifest["observed_at"],
        }
    )

    floors = []
    nodes = []
    edges = []
    assets = [
        {
            "id": "brown-house-corridors",
            "label": "Brown House corridor network",
            "kind": "path",
            "position": None,
            "source_id": source_ids["426-01.pdf"],
            "aliases": ["Brown House hallways"],
        },
        {
            "id": "brown-house-mapped-elevator",
            "label": "Brown House mapped elevator location",
            "kind": "elevator",
            "position": {"lat": 42.39741739380068, "lng": -72.52296170086319},
            "source_id": accessibility_source_id,
            "aliases": ["UMass elevator OBJECTID 186"],
        },
    ]

    for floor in FLOOR_ORDER:
        record = _source_for_floor(records, floor)
        source_id = source_ids[record["name"]]
        floor_id = "b" if floor == "basement" else floor
        floors.append(
            {
                "id": floor_id,
                "label": _floor_label(floor),
                "coordinate_system": "image_pixels",
                "image_url": None,
                "image_width": record["trace"]["page_width"],
                "image_height": record["trace"]["page_height"],
                "source_id": source_id,
                "aliases": [floor],
            }
        )
        junction_x = set(SPINE_X)
        for room in _candidate_rooms(record, floor):
            junction_x.add(round(room["x"], 3))
        ordered_x = sorted(junction_x)
        for x in ordered_x:
            nodes.append(
                {
                    "id": f"junction-{floor_id}-{x:g}",
                    "label": f"Brown House corridor junction ({x:g})",
                    "floor_id": floor_id,
                    "kind": "junction",
                    "x": x,
                    "y": SPINE_Y,
                    "position": None,
                    "source_id": source_id,
                    "aliases": [],
                    "source_record_ids": [record["server_relative_url"]],
                }
            )
        for left, right in zip(ordered_x, ordered_x[1:], strict=False):
            edges.append(
                {
                    "id": f"corridor-{floor_id}-{left:g}-{right:g}",
                    "start": f"junction-{floor_id}-{left:g}",
                    "end": f"junction-{floor_id}-{right:g}",
                    "kind": "corridor",
                    "length_m": max(round((right - left) * 0.0254, 2), 0.01),
                    "geometry": [(left, SPINE_Y), (right, SPINE_Y)],
                    "asset_id": "brown-house-corridors",
                    "bidirectional": True,
                    "public_access": True,
                    "step_free": True,
                    "grade_percent": 0.0,
                    "width_m": None,
                    "door_type": "unknown",
                    "source_id": source_id,
                    "evidence": (
                        f"Main corridor centerline traced from {record['name']} "
                        "official Residential Life plan; doorway review pending."
                    ),
                }
            )
        for room in _candidate_rooms(record, floor):
            room_id = f"room-{floor_id}-{room['label'].lower()}"
            door_y = 315.0 if room["y"] < SPINE_Y else 345.0
            x = round(room["x"], 3)
            nodes.append(
                {
                    "id": room_id,
                    "label": f"Room {room['label']}",
                    "floor_id": floor_id,
                    "kind": "room",
                    "x": x,
                    "y": door_y,
                    "position": None,
                    "source_id": source_id,
                    "aliases": [room["label"]],
                    "source_record_ids": [record["server_relative_url"]],
                }
            )
            edges.append(
                {
                    "id": f"door-{floor_id}-{room['label'].lower()}",
                    "start": room_id,
                    "end": f"junction-{floor_id}-{x:g}",
                    "kind": "door",
                    "length_m": 0.5,
                    "geometry": [(x, door_y), (x, SPINE_Y)],
                    "asset_id": None,
                    "bidirectional": True,
                    "public_access": True,
                    "step_free": True,
                    "grade_percent": 0.0,
                    "width_m": None,
                    "door_type": "unknown",
                    "source_id": source_id,
                    "evidence": (
                        f"Room threshold position traced from visible doorway on {record['name']}; "
                        "final clearance requires field review."
                    ),
                }
            )
        for side, x in (("west", 90.0), ("east", 705.0)):
            nodes.append(
                {
                    "id": f"stairs-{floor_id}-{side}",
                    "label": f"{side.title()} stair landing",
                    "floor_id": floor_id,
                    "kind": "stair_landing",
                    "x": x,
                    "y": SPINE_Y,
                    "position": None,
                    "source_id": source_id,
                    "aliases": ["UP DN"],
                    "source_record_ids": [record["server_relative_url"]],
                }
            )
            edges.append(
                {
                    "id": f"stair-landing-corridor-{floor_id}-{side}",
                    "start": f"stairs-{floor_id}-{side}",
                    "end": f"junction-{floor_id}-{x:g}",
                    "kind": "corridor",
                    "length_m": 0.01,
                    "geometry": [(x, SPINE_Y), (x, SPINE_Y)],
                    "asset_id": "brown-house-corridors",
                    "bidirectional": True,
                    "public_access": True,
                    "step_free": True,
                    "grade_percent": 0.0,
                    "width_m": None,
                    "door_type": "unknown",
                    "source_id": source_id,
                    "evidence": (
                        f"Stair landing joins the main corridor at the {side} end "
                        f"of {record['name']}."
                    ),
                }
            )

    for lower, upper in zip(FLOOR_ORDER, FLOOR_ORDER[1:], strict=False):
        lower_id = "b" if lower == "basement" else lower
        upper_id = "b" if upper == "basement" else upper
        source_id = source_ids[_source_for_floor(records, upper)["name"]]
        for side in ("west", "east"):
            edges.append(
                {
                    "id": f"stairs-{lower_id}-{upper_id}-{side}",
                    "start": f"stairs-{lower_id}-{side}",
                    "end": f"stairs-{upper_id}-{side}",
                    "kind": "steps",
                    "length_m": 3.5,
                    "geometry": None,
                    "asset_id": None,
                    "bidirectional": True,
                    "public_access": True,
                    "step_free": False,
                    "grade_percent": None,
                    "width_m": None,
                    "door_type": "unknown",
                    "source_id": source_id,
                    "evidence": (
                        f"UP/DN stair landing shown on {source_id}; exact rise and "
                        "accessible alternative require building verification."
                    ),
                }
            )

    payload = {
        "version": 1,
        "building_id": BUILDING,
        "name": "Brown House",
        "synthetic": False,
        "status": "draft",
        "reviewed_at": None,
        "review_notes": (
            "Draft generated from official UMass Residential Life plans. "
            "Corridor and doorway traces require human review before production use; "
            "the public accessibility map identifies an elevator and an entrance marked "
            "accessible to all floors, but it does not establish their exact floor-plan "
            "shaft, stops, doorway, or outdoor graph binding. No accessible vertical "
            "connection is claimed until those links are reviewed."
        ),
        "sources": sources,
        "floors": floors,
        "nodes": nodes,
        "assets": assets,
        "edges": edges,
        "portals": [],
        "maneuvers": [],
    }
    atomic_json(output, payload)
    return payload


def build(manifest_path: Path, output: Path):
    """Create the corrected draft without the old projected doorway/scale assumptions.

    Keep the earlier helper as an explicitly named historical implementation.
    Its generated edges must not be used as evidence of physical connectivity.
    """
    from campus_notices.residence_workspace import source_floors
    from campus_routing.indoor import IndoorMap

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = [
        r for r in manifest["records"] if r["area"] == "Sylvan" and r["building"] == "Brown Hall"
    ]
    if not records:
        raise ValueError("Brown source plans missing")
    sources, floors = [], {}
    for record in records:
        sid = "brown-" + Path(record["name"]).stem.lower().replace(".", "-")
        sources.append(
            dict(
                id=sid,
                url=_source_url(record["server_relative_url"]),
                edition=record["name"],
                observed_at=manifest["observed_at"],
            )
        )
        for floor in source_floors(record):
            fid = "b" if floor == "basement" else floor
            floors[fid] = dict(
                id=fid,
                label="Basement" if fid == "b" else f"Floor {fid}",
                source_id=sid,
                coordinate_system="image_pixels",
            )
    data = IndoorMap.model_validate(
        dict(
            building_id=BUILDING,
            name="Brown House",
            status="draft",
            sources=sources,
            floors=list(floors.values()),
            review_notes="Corrected source-only draft: removed unsupported room-to-corridor "
            "projections, assumed meter scale, zero grades and all-floor elevator stops. "
            "Trace suite doors and corridors from the actual plans, document scale, access, "
            "stops and entrance alignment. Room label candidates remain in the private workspace.",
        )
    )
    payload = data.model_dump(mode="json")
    atomic_json(output, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/traces/brown-house-corrected.json",
    )
    args = parser.parse_args()
    payload = build(args.manifest, args.output)
    print(
        f"Built draft {payload['building_id']}: "
        f"{len(payload['floors'])} floors, {len(payload['nodes'])} nodes, "
        f"{len(payload['edges'])} edges"
    )


if __name__ == "__main__":
    main()
