"""Add a small, source-linked room pilot to the reviewed indoor maps.

The public sources identify these destinations and floors, but do not provide
survey-grade doorway coordinates. The generated waypoints are therefore
published as pilot mappings and the router warns when a room waypoint is used.
"""

import argparse
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.indoor import IndoorMap, read_indoor

ROOT = Path(__file__).resolve().parents[1]

PILOTS = {
    "library": {
        "floor_id": "2nd-floor",
        "node": {
            "id": "lib-room-recess-2",
            "label": "Recess / Quiet Study, 2nd Floor",
            "kind": "room",
            "x": 10.0,
            "y": 35.0,
            "aliases": ["recess", "quiet study", "room recess"],
            "source_id": "library-floorplans",
            "source_record_ids": ["2f9cf0cb673d6873f4c3"],
        },
        "edge": {
            "id": "lib-corridor-lobby-recess-2",
            "start": "lib-lobby-2nd-floor",
            "end": "lib-room-recess-2",
            "kind": "corridor",
            "length_m": 35.0,
            "geometry": [[10.0, 0.0], [10.0, 35.0]],
            "source_id": "library-floorplans",
            "evidence": (
                "Pilot waypoint for the source directory's Quiet Study, RECESS record "
                "(2nd floor). Doorway position and scale require field verification."
            ),
        },
        "note": (
            "Includes one source-linked 2nd-floor Recess/Quiet Study pilot waypoint; "
            "its doorway position is not survey-grade and must be field-verified."
        ),
    },
    "ilc": {
        "floor_id": "2",
        "node": {
            "id": "ilc-room-n151-f2",
            "label": "ILC N151, 2nd-floor entryway",
            "kind": "room",
            "x": 10.0,
            "y": 18.0,
            "aliases": ["n151", "room n151", "n 151"],
            "source_id": "ilc-classrooms",
            "source_record_ids": ["7b143d7104bea7017cfd"],
        },
        "edge": {
            "id": "ilc-corridor-junction-n151-f2",
            "start": "ilc-junction-f2",
            "end": "ilc-room-n151-f2",
            "kind": "corridor",
            "length_m": 18.0,
            "geometry": [[10.0, 0.0], [10.0, 18.0]],
            "source_id": "ilc-classrooms",
            "evidence": (
                "Pilot waypoint for the registrar's N151 record, which explicitly "
                "documents entryways from floors 1 and 2. Doorway position requires "
                "field verification."
            ),
        },
        "note": (
            "Includes the source-linked N151 2nd-floor entryway pilot waypoint; "
            "its doorway position is not survey-grade and must be field-verified."
        ),
    },
}


def enable_rooms(folder: Path) -> list[Path]:
    updated = []
    for building_id, pilot in PILOTS.items():
        path = folder / f"{building_id}.json"
        data = read_indoor(path)
        node = pilot["node"] | {"floor_id": pilot["floor_id"], "position": None}
        edge = pilot["edge"] | {
            "asset_id": None,
            "bidirectional": True,
            "public_access": True,
            "step_free": True,
            "grade_percent": 0.0,
            "width_m": 2.5,
            "door_type": "unknown",
        }
        nodes = [item for item in data.nodes if item.id != node["id"]]
        edges = [item for item in data.edges if item.id != edge["id"]]
        nodes.append(node)
        edges.append(edge)
        notes = f"{data.review_notes.strip()} {pilot['note']}"
        updated_map = IndoorMap.model_validate(
            data.model_dump(mode="json")
            | {
                "nodes": nodes,
                "edges": edges,
                "review_notes": notes,
            }
        )
        atomic_json(path, updated_map.model_dump(mode="json"))
        updated.append(path)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "data/indoor")
    args = parser.parse_args()
    for path in enable_rooms(args.folder):
        print(path)


if __name__ == "__main__":
    main()
