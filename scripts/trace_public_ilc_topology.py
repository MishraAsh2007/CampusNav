"""Anchor the ILC room graph to the public scaled first/second-floor plans.

The public ArcGIS layers provide the authoritative floor geometry. This trace
uses explicit plan coordinates and corridor polylines; it does not infer a
room position from its number.
"""

import argparse
import math
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.indoor import read_indoor

ROOT = Path(__file__).resolve().parents[1]
PLAN_SOURCE = "ilc-floorplans"
PLAN_SCALE_M_PER_PIXEL = 0.14929107082380833

POINTS = {
    "1": {
        "ilc-elev-west-f1": (690.0, 715.0),
        "ilc-elev-east-f1": (805.0, 715.0),
        "ilc-junction-f1": (748.0, 770.0),
        "ilc-entrance-south": (770.0, 900.0),
        "ilc-entrance-west": (485.0, 700.0),
        "ilc-source-n111-f1": (555.0, 775.0),
        "ilc-source-n155-f1": (590.0, 405.0),
        "ilc-source-n101-f1": (555.0, 965.0),
        "ilc-source-s140-f1": (690.0, 965.0),
        "ilc-source-s120-f1": (835.0, 960.0),
        "ilc-source-s131-f1": (900.0, 770.0),
        "ilc-source-s110-f1": (1030.0, 955.0),
    },
    "2": {
        "ilc-elev-west-f2": (690.0, 730.0),
        "ilc-elev-east-f2": (805.0, 730.0),
        "ilc-junction-f2": (750.0, 780.0),
        "ilc-source-n255-f2": (585.0, 405.0),
        "ilc-source-s240-f2": (700.0, 930.0),
        "ilc-source-n211-f2": (555.0, 805.0),
        "ilc-source-s220-f2": (965.0, 930.0),
        "ilc-source-s211-f2": (1040.0, 755.0),
        "ilc-source-s231-f2": (870.0, 755.0),
        "ilc-source-n151-f2": (610.0, 560.0),
    },
}

ROOM_PATHS = {
    "ilc-source-n111-f1": [(555, 775), (620, 775), (690, 770), (748, 770)],
    "ilc-source-n155-f1": [(590, 405), (625, 520), (690, 650), (748, 770)],
    "ilc-source-n101-f1": [(555, 965), (610, 900), (690, 820), (748, 770)],
    "ilc-source-s140-f1": [(690, 965), (700, 900), (748, 770)],
    "ilc-source-s120-f1": [(835, 960), (835, 885), (790, 820), (748, 770)],
    "ilc-source-s131-f1": [(900, 770), (850, 770), (748, 770)],
    "ilc-source-s110-f1": [(1030, 955), (965, 875), (830, 810), (748, 770)],
    "ilc-source-n255-f2": [(585, 405), (635, 540), (690, 665), (750, 780)],
    "ilc-source-s240-f2": [(700, 930), (720, 870), (750, 780)],
    "ilc-source-n211-f2": [(555, 805), (640, 805), (700, 780), (750, 780)],
    "ilc-source-s220-f2": [(965, 930), (900, 865), (820, 810), (750, 780)],
    "ilc-source-s211-f2": [(1040, 755), (950, 755), (820, 780), (750, 780)],
    "ilc-source-s231-f2": [(870, 755), (820, 755), (750, 780)],
    "ilc-source-n151-f2": [(610, 560), (665, 630), (700, 700), (750, 780)],
}


def distance(points):
    return round(
        sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
        * PLAN_SCALE_M_PER_PIXEL,
        2,
    )


def trace(path):
    data = read_indoor(path).model_dump(mode="json")
    nodes = {node["id"]: node for node in data["nodes"]}
    for floor_id, points in POINTS.items():
        floor = next(f for f in data["floors"] if f["id"] == floor_id)
        floor["coordinate_system"] = "image_pixels"
        floor["image_width"] = 1536
        floor["image_height"] = 1280
        floor["source_id"] = PLAN_SOURCE
        for node_id, point in points.items():
            nodes[node_id]["x"], nodes[node_id]["y"] = point

    for edge in data["edges"]:
        start = nodes[edge["start"]]
        end = nodes[edge["end"]]
        if start["floor_id"] != end["floor_id"]:
            continue
        if start["floor_id"] not in POINTS:
            continue  # Floors 3/4 have no plan trace in this script.
        points = ROOM_PATHS.get(edge["start"])
        if points is None:
            points = ROOM_PATHS.get(edge["end"])
            if points is not None:
                points = list(reversed(points))
        if points is None:
            points = [
                [start["x"], start["y"]],
                [end["x"], end["y"]],
            ]
        edge["geometry"] = [list(point) for point in points]
        edge["length_m"] = distance(points)
        edge["source_id"] = PLAN_SOURCE
        edge["evidence"] = (
            "Corridor polyline traced against the public scaled ILC floor plan; "
            "doorway clearance and current obstruction status require field verification."
        )

    data["nodes"] = list(nodes.values())
    data["review_notes"] = (
        data["review_notes"] + " ILC floors 1 and 2 are now anchored to the public scaled ArcGIS "
        "floor plans with explicit room-to-corridor polylines. Doorway clearance "
        "and obstruction status still require field verification."
    )
    atomic_json(path, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=ROOT / "data/indoor/ilc.json")
    args = parser.parse_args()
    trace(args.map)
    print(args.map)


if __name__ == "__main__":
    main()
