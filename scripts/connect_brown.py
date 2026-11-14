"""Connect the Brown House indoor draft to mapped accessibility and outdoor evidence."""

import argparse
import json
import math
from pathlib import Path

from campus_notices.cache import atomic_json

ROOT = Path(__file__).resolve().parents[1]
BROWN_ENTRANCE = {"lat": 42.397319084921826, "lng": -72.52277666581294}
BROWN_OUTDOOR_NODE = 12881595796
ELEVATOR_X = 301.0
CORRIDOR_Y = 330.0


def _floor_ids(payload):
    return [floor["id"] for floor in payload["floors"]]


def _nearest_junction(payload, floor_id, x):
    candidates = [
        node
        for node in payload["nodes"]
        if node["floor_id"] == floor_id and node["kind"] == "junction"
    ]
    return min(candidates, key=lambda node: abs(node["x"] - x))


def _add_node(payload, node):
    payload["nodes"].append(node)


def _add_edge(payload, edge):
    payload["edges"].append(edge)


def connect(source: Path, output: Path):
    # The old automatic projection guessed a shaft on every floor and a straight
    # entrance approach. A reviewed trace must supply these before a portal is joined.
    raise ValueError(
        "Automatic Brown elevator/entrance inference is disabled. Trace and review the "
        "actual stops, suite doors and outdoor approach; use scripts.import_indoor "
        "with the reviewed map. Earlier candidate files remain private drafts."
    )


def legacy_unverified_connect(source: Path, output: Path):
    """Historical candidate generation only; not used by the command-line entry point."""
    payload = json.loads(source.read_text(encoding="utf-8"))
    source_id = "brown-house-accessibility-map"
    plan_source = "brown-house-426-01"
    entrance_id = "entrance-brown-accessible"
    if entrance_id not in {node["id"] for node in payload["nodes"]}:
        _add_node(
            payload,
            {
                "id": entrance_id,
                "label": "Accessible Brown House entrance (mapped entrance OBJECTID 3)",
                "floor_id": "1",
                "kind": "entrance",
                "x": 220.0,
                "y": 405.0,
                "position": BROWN_ENTRANCE,
                "source_id": source_id,
                "aliases": ["Brown House accessible entrance"],
                "source_record_ids": ["entrance OBJECTID 3"],
            },
        )
        _add_edge(
            payload,
            {
                "id": "entrance-brown-accessible-to-corridor",
                "start": entrance_id,
                "end": "junction-1-220",
                "kind": "door",
                "length_m": 1.9,
                "geometry": [(220.0, 405.0), (220.0, CORRIDOR_Y)],
                "asset_id": None,
                "bidirectional": True,
                "public_access": True,
                "step_free": True,
                "grade_percent": 0.0,
                "width_m": None,
                "door_type": "unknown",
                "source_id": plan_source,
                "evidence": (
                    "Candidate exterior doorway aligned to the south-side first-floor "
                    "door group on the official 426-01 plan; exact doorway and clearance "
                    "require field or facilities-plan confirmation."
                ),
            },
        )

    elevator_id = "brown-house-mapped-elevator"
    existing_nodes = {node["id"] for node in payload["nodes"]}
    floor_ids = _floor_ids(payload)
    for floor_id in floor_ids:
        stop_id = f"elevator-stop-{floor_id}"
        if stop_id in existing_nodes:
            continue
        junction = _nearest_junction(payload, floor_id, ELEVATOR_X)
        _add_node(
            payload,
            {
                "id": stop_id,
                "label": f"Candidate Brown House elevator stop ({floor_id})",
                "floor_id": floor_id,
                "kind": "elevator_stop",
                "x": ELEVATOR_X,
                "y": CORRIDOR_Y,
                "position": None,
                "source_id": plan_source,
                "aliases": ["Candidate elevator shaft"],
                "source_record_ids": ["426-01.pdf", "426-02.03.04.05.06.07.08.pdf"],
            },
        )
        _add_edge(
            payload,
            {
                "id": f"elevator-stop-{floor_id}-to-corridor",
                "start": stop_id,
                "end": junction["id"],
                "kind": "corridor",
                "length_m": max(abs(ELEVATOR_X - junction["x"]) * 0.0254, 0.01),
                "geometry": [(ELEVATOR_X, CORRIDOR_Y), (junction["x"], junction["y"])],
                "asset_id": "brown-house-corridors",
                "bidirectional": True,
                "public_access": True,
                "step_free": True,
                "grade_percent": 0.0,
                "width_m": None,
                "door_type": "unknown",
                "source_id": plan_source,
                "evidence": (
                    "Candidate elevator stop aligned to repeated shaft geometry in the "
                    "official residence plans; exact shaft and doorway require review."
                ),
            },
        )
        existing_nodes.add(stop_id)

    existing_edges = {edge["id"] for edge in payload["edges"]}
    for lower, upper in zip(floor_ids, floor_ids[1:], strict=False):
        edge_id = f"elevator-{lower}-{upper}"
        if edge_id in existing_edges:
            continue
        _add_edge(
            payload,
            {
                "id": edge_id,
                "start": f"elevator-stop-{lower}",
                "end": f"elevator-stop-{upper}",
                "kind": "elevator",
                "length_m": 3.5,
                "geometry": None,
                "asset_id": elevator_id,
                "bidirectional": True,
                "public_access": True,
                "step_free": True,
                "grade_percent": None,
                "width_m": None,
                "door_type": "unknown",
                "source_id": source_id,
                "evidence": (
                    "Vertical elevator connection is a draft inference from the mapped "
                    "elevator asset and repeated plan geometry; floor stops require "
                    "facilities or field verification."
                ),
            },
        )

    portal_id = "brown-house-accessible-entrance-portal"
    payload["portals"] = [portal for portal in payload["portals"] if portal["id"] != portal_id]
    outdoor = (BROWN_OUTDOOR_NODE, 42.3973285, -72.5226772)
    distance_m = math.hypot(
        (outdoor[2] - BROWN_ENTRANCE["lng"])
        * 111320
        * math.cos(math.radians(BROWN_ENTRANCE["lat"])),
        (outdoor[1] - BROWN_ENTRANCE["lat"]) * 111320,
    )
    payload["portals"].append(
        {
            "id": portal_id,
            "indoor_node_id": entrance_id,
            "outdoor_node_id": BROWN_OUTDOOR_NODE,
            "geometry": [
                [BROWN_ENTRANCE["lng"], BROWN_ENTRANCE["lat"]],
                [outdoor[2], outdoor[1]],
            ],
            "length_m": round(distance_m, 2),
            "public_access": True,
            "step_free": True,
            "grade_percent": None,
            "width_m": None,
            "door_type": "unknown",
            "asset_id": None,
            "source_id": source_id,
            "evidence": (
                "Portal uses mapped Brown House accessible entrance OBJECTID 3 and the "
                "nearest connected node in the private OSM extension graph. The final "
                "entrance-to-node path and doorway alignment require field review."
            ),
        }
    )
    payload["review_notes"] = (
        "Brown House is connected to the private extended outdoor graph through the "
        "mapped accessible entrance. Candidate entrance and elevator-stop geometry is "
        "source-backed but not field-verified; elevator floor stops, doorway clearance, "
        "and exact plan-to-map alignment remain review requirements. Keep status=draft."
    )
    atomic_json(output, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/traces/brown-house.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/traces/brown-house-connected.json",
    )
    args = parser.parse_args()
    payload = connect(args.source, args.output)
    print(f"Saved {args.output}: {len(payload['nodes'])} nodes, {len(payload['edges'])} edges")


if __name__ == "__main__":
    main()
