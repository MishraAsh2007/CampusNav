"""Create a private, inspected same-floor room-to-room wayfinding pilot for Brett."""

import argparse
import hashlib
import json
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.plan_wayfinding import PlanWayfindingMap, PlanWayfindingRequest, plan_directions
from scripts.build_brown_trace import _source_url

ROOT = Path(__file__).resolve().parents[1]


def build(source_url, checksum):
    # PDF-point positions inspected on the first-floor drawing. North/south room
    # thresholds connect to distinct junctions along the same continuous hall.
    rooms = [
        ("101", 111, 370),
        ("103", 144, 370),
        ("105", 198, 369),
        ("107", 229, 369),
        ("109", 264, 369),
        ("111", 294, 370),
        ("102", 111, 354),
        ("104", 144, 354),
        ("106", 174, 354),
        ("108", 202, 354),
    ]
    nodes = []
    edges = []
    xs = sorted({x for _, x, _ in rooms})
    for x in xs:
        nearby = "/".join(room for room, rx, _ in rooms if rx == x)
        nodes.append(dict(id=f"hall-{x}", label=f"the hall outside Room {nearby}", x=x, y=362))
    for a, b in zip(xs, xs[1:], strict=False):
        edges.append(
            dict(
                id=f"hall-{a}-{b}",
                start=f"hall-{a}",
                end=f"hall-{b}",
                kind="corridor",
                asset_id="brett-first-west-hall",
                evidence="Continuous visible first-floor hall between room rows; "
                "no stairs crossed.",
            )
        )
    for room, x, y in rooms:
        node = f"room-{room}"
        nodes.append(dict(id=node, label=f"Room {room} threshold", x=x, y=y))
        edges.append(
            dict(
                id=f"door-{room}",
                start=node,
                end=f"hall-{x}",
                kind="door",
                asset_id=f"brett-door-{room}",
                evidence="Visible room-to-main-hall doorway in the 295-01 first-floor plan; "
                "clearance unknown.",
            )
        )
    return PlanWayfindingMap(
        building_id="brett",
        floor_id="1",
        source_url=source_url,
        source_sha256=checksum,
        nodes=nodes,
        connections=edges,
        drawing_review="Inspected first-floor west-wing corridor and doorway connections only. "
        "Not a survey or confirmation of current operation or accessibility.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="Room number within the traced first-floor segment")
    parser.add_argument("--end", help="Room number within the traced first-floor segment")
    parser.add_argument("--accept-drawing-only", action="store_true")
    parser.add_argument("--resident-access-confirmed", action="store_true")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("Provide both --start and --end")
    manifest = json.loads((ROOT / "data/private/residence_floorplans/manifest.json").read_text())
    record = next(r for r in manifest["records"] if r["name"] == "295-01.pdf")
    checksum = hashlib.sha256(Path(record["local_path"]).read_bytes()).hexdigest()
    if checksum != record["sha256"]:
        raise ValueError("Source plan changed; inspect before tracing")
    data = build(_source_url(record["server_relative_url"]), checksum)
    result = (
        plan_directions(
            data,
            PlanWayfindingRequest(
                start_node_id="room-" + args.start,
                end_node_id="room-" + args.end,
                accept_drawing_only=args.accept_drawing_only,
                resident_access_confirmed=args.resident_access_confirmed,
            ),
        )
        if args.start
        else None
    )
    output = ROOT / "data/private/residence_floorplans/workspaces/brett/first-floor-wayfinding"
    atomic_json(output / "map.json", data.model_dump(mode="json"))
    if result:
        atomic_json(output / "last-request-result.json", result)
    print(
        "Created",
        len(data.nodes),
        "nodes and",
        len(data.connections),
        "drawing connections:",
        output,
    )
    for step in result["steps"] if result else []:
        print(step["instruction"])
    print("Same floor only; distances and physical accessibility unverified.")


if __name__ == "__main__":
    main()
