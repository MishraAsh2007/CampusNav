"""Expand the two-building indoor maps from source records for the hackathon.

Public sources identify these destinations and floors, but do not provide
survey-grade doorway coordinates. This generator creates explicit, repeatable
pilot waypoints so the complete building flow can be demonstrated while the
router continues to warn that final approaches need field verification.
"""

import argparse
import json
import re
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.indoor import IndoorMap, read_indoor

ROOT = Path(__file__).resolve().parents[1]

ILC_ROOM_FLOORS = {
    "N101": ["1"],
    "N111": ["1"],
    "N151": ["1", "2"],
    "N155": ["1"],
    "S110": ["1"],
    "S120": ["1"],
    "S131": ["1"],
    "S140": ["1"],
    "N211": ["2"],
    "S211": ["2"],
    "S220": ["2"],
    "S231": ["2"],
    "S240": ["2"],
    "N255": ["2"],
    "S311": ["3"],
    "S331": ["3"],
}


def floor_key(label):
    normalized = str(label).strip().casefold()
    if normalized in {"e", "lower level", "ll"}:
        return "lower-level"
    if normalized.isdigit():
        number = int(normalized)
        suffix = (
            "th" if 10 < number % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
        )
        return f"{number}{suffix}-floor"
    match = re.search(r"(\d+)", normalized)
    if match:
        return floor_key(match.group(1))
    return normalized.replace(" ", "-")


def ordinal(number):
    suffix = "th" if 10 < number % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def aliases(label):
    value = str(label).replace(",", " ")
    return list(dict.fromkeys([value.casefold(), *re.findall(r"[A-Za-z0-9]+", value.casefold())]))


def add_source(source_rows, source_id, url, observed_at):
    if any(row["id"] == source_id for row in source_rows):
        return source_rows
    return [
        *source_rows,
        {
            "id": source_id,
            "url": url,
            "edition": "Not stated by source",
            "observed_at": observed_at,
        },
    ]


def add_destination(
    nodes, edges, *, node_id, label, floor_id, source_id, record_id, x, y, anchor_id
):
    removed = {
        node["id"]
        for node in nodes
        if node["id"] == node_id or record_id in node.get("source_record_ids", [])
    }
    nodes = [node for node in nodes if node["id"] not in removed]
    edges = [
        edge
        for edge in edges
        if edge["id"] != f"{node_id}-edge"
        and edge["start"] not in removed
        and edge["end"] not in removed
    ]
    nodes.append(
        {
            "id": node_id,
            "label": label,
            "floor_id": floor_id,
            "kind": "room",
            "x": x,
            "y": y,
            "position": None,
            "source_id": source_id,
            "aliases": aliases(label),
            "source_record_ids": [record_id],
        }
    )
    length = max(1.0, ((x - 10.0) ** 2 + y**2) ** 0.5)
    edges.append(
        {
            "id": f"{node_id}-edge",
            "start": anchor_id,
            "end": node_id,
            "kind": "corridor",
            "length_m": round(length, 2),
            "geometry": [[10.0, 0.0], [x, y]],
            "asset_id": None,
            "bidirectional": True,
            "public_access": True,
            "step_free": True,
            "grade_percent": 0.0,
            "width_m": 2.5,
            "door_type": "unknown",
            "source_id": source_id,
            "evidence": (
                "Hackathon pilot waypoint linked to the source record. "
                "Coordinates are repeatable approximations, not a survey; "
                "field-verify the doorway and final approach."
            ),
        }
    )
    return nodes, edges


def ensure_library_floor(data, floor_id):
    if floor_id in {floor["id"] for floor in data["floors"]}:
        return data
    number = floor_id.split("-", 1)[0]
    data["floors"].append(
        {
            "id": floor_id,
            "label": f"{ordinal(int(number))} Floor",
            "coordinate_system": "local_meters",
            "image_url": None,
            "image_width": None,
            "image_height": None,
            "source_id": "library-directory",
            "aliases": [number, f"{number} floor"],
        }
    )
    data["nodes"].extend(
        [
            {
                "id": f"lib-elev-{floor_id}",
                "label": f"Elevator, {ordinal(int(number))} Floor",
                "floor_id": floor_id,
                "kind": "elevator_stop",
                "x": 0.0,
                "y": 0.0,
                "position": None,
                "source_id": "umass-arcgis-access",
                "aliases": [],
                "source_record_ids": [],
            },
            {
                "id": f"lib-lobby-{floor_id}",
                "label": f"Lobby, {number}rd Floor",
                "floor_id": floor_id,
                "kind": "junction",
                "x": 10.0,
                "y": 0.0,
                "position": None,
                "source_id": "umass-arcgis-access",
                "aliases": [],
                "source_record_ids": [],
            },
        ]
    )
    data["edges"].extend(
        [
            {
                "id": f"lib-corridor-elev-lobby-{floor_id}",
                "start": f"lib-elev-{floor_id}",
                "end": f"lib-lobby-{floor_id}",
                "kind": "corridor",
                "length_m": 10.0,
                "geometry": [[0.0, 0.0], [10.0, 0.0]],
                "asset_id": None,
                "bidirectional": True,
                "public_access": True,
                "step_free": True,
                "grade_percent": 0.0,
                "width_m": 2.5,
                "door_type": "unknown",
                "source_id": "umass-arcgis-access",
                "evidence": "Hackathon pilot floor connector; verify against the building plan.",
            },
        ]
    )
    for adjacent in ("2nd-floor", "4th-floor"):
        adjacent_node = f"lib-elev-{adjacent}"
        if any(
            edge["start"] == adjacent_node and edge["end"] == f"lib-elev-{floor_id}"
            for edge in data["edges"]
        ):
            continue
        data["edges"].append(
            {
                "id": f"lib-elevator-{adjacent}-{floor_id}",
                "start": adjacent_node,
                "end": f"lib-elev-{floor_id}",
                "kind": "elevator",
                "length_m": 4.0,
                "geometry": None,
                "asset_id": "library-elevator-main",
                "bidirectional": True,
                "public_access": True,
                "step_free": True,
                "grade_percent": None,
                "width_m": None,
                "door_type": "automatic",
                "source_id": "umass-arcgis-access",
                "evidence": "Hackathon pilot elevator stop; verify floor service in the building.",
            }
        )
    return data


def expand(folder: Path, source_path: Path):
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    records = payload["records"]
    updated = []

    library = read_indoor(folder / "library.json")
    library_records = [
        row
        for row in records
        if row["building_id"] == "library" and row["kind"] == "floor_directory"
    ]
    library_dict = library.model_dump(mode="json")
    source_observed = library_records[0]["observed_at"]
    library_dict["sources"] = add_source(
        library_dict["sources"],
        "library-directory",
        "https://www.library.umass.edu/du-bois-library/",
        source_observed,
    )
    library_floor_ids = {floor_key(row["floor_label"]) for row in library_records}
    for floor_id in sorted(library_floor_ids):
        library_dict = ensure_library_floor(library_dict, floor_id)
    nodes, edges = library_dict["nodes"], library_dict["edges"]
    per_floor = {}
    for row in library_records:
        floor_id = floor_key(row["floor_label"])
        index = per_floor.get(floor_id, 0)
        per_floor[floor_id] = index + 1
        x, y = 20.0 + (index % 4) * 12.0, 15.0 + (index // 4) * 10.0
        nodes, edges = add_destination(
            nodes,
            edges,
            node_id=f"lib-source-{row['id']}",
            label=f"{row['label']} ({row['floor_label']})",
            floor_id=floor_id,
            source_id="library-directory",
            record_id=row["id"],
            x=x,
            y=y,
            anchor_id=f"lib-lobby-{floor_id}",
        )
    library_dict["nodes"], library_dict["edges"] = nodes, edges
    library_dict["review_notes"] = (
        f"{library.review_notes} Expanded to {len(library_records)} source-linked "
        "floor destinations; coordinates are hackathon pilot approximations requiring "
        "field verification."
    )
    atomic_json(
        folder / "library.json", IndoorMap.model_validate(library_dict).model_dump(mode="json")
    )
    updated.append(folder / "library.json")

    ilc = read_indoor(folder / "ilc.json")
    ilc_records = [
        row for row in records if row["building_id"] == "ilc" and row["kind"] == "room_directory"
    ]
    ilc_dict = ilc.model_dump(mode="json")
    nodes, edges = ilc_dict["nodes"], ilc_dict["edges"]
    per_floor = {}
    for row in ilc_records:
        room = row["room_id"]
        floors = ILC_ROOM_FLOORS[room]
        for floor_id in floors:
            index = per_floor.get(floor_id, 0)
            per_floor[floor_id] = index + 1
            x = -15.0 if room.startswith("N") else 35.0
            y = 15.0 + index * 8.0
            nodes, edges = add_destination(
                nodes,
                edges,
                node_id=f"ilc-source-{room.casefold()}-f{floor_id}",
                label=f"ILC {room}, {ordinal(int(floor_id))} Floor entryway",
                floor_id=floor_id,
                source_id="ilc-classrooms",
                record_id=row["id"],
                x=x,
                y=y,
                anchor_id=f"ilc-junction-f{floor_id}",
            )
    ilc_dict["nodes"], ilc_dict["edges"] = nodes, edges
    ilc_dict["review_notes"] = (
        f"{ilc.review_notes} Expanded to {len(ilc_records)} source-linked classroom "
        "records across documented pilot floors; coordinates are hackathon pilot "
        "approximations requiring field verification."
    )
    atomic_json(folder / "ilc.json", IndoorMap.model_validate(ilc_dict).model_dump(mode="json"))
    updated.append(folder / "ilc.json")
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "data/indoor")
    parser.add_argument("--sources", type=Path, default=ROOT / "data/indoor_sources.json")
    args = parser.parse_args()
    for path in expand(args.folder, args.sources):
        print(path)


if __name__ == "__main__":
    main()
