"""Deterministic walking maneuvers from the selected, directed metric polylines.

Same-name paths can turn. Sparse OSM names therefore never determine where a
maneuver starts. Very short cartographic zigzags need support from a 4 m approach
and departure before becoming spoken turns. No road crossings are invented.
"""

import math
from itertools import pairwise

from shapely.geometry import LineString


def angle(a, b):
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))


def turn_code(degrees):
    size = abs(degrees)
    side = "left" if degrees > 0 else "right"
    if size >= 165:
        return "u-turn"
    if size >= 115:
        return f"sharp-{side}"
    if size >= 45:
        return side
    if size >= 30:
        return f"slight-{side}"
    return None


def _name(value):
    if isinstance(value, list):
        value = "/".join(str(item) for item in value if item)
    return str(value).strip() if value else "the mapped path"


def walking_directions(edges, to_lnglat, endpoint):
    pieces = []
    for edge in edges:
        points = list(edge["line"].coords)
        lengths = [math.dist(a, b) for a, b in pairwise(points)]
        total = sum(lengths)
        if total <= 1e-8:
            continue
        for (a, b), length in zip(pairwise(points), lengths, strict=True):
            if length <= 1e-8:
                continue
            pieces.append(
                dict(
                    a=a,
                    b=b,
                    length=edge["length"] * length / total,
                    kind=edge.get("kind", "path"),
                    name=_name(edge.get("name")),
                    grade=edge.get("grade_percent"),
                )
            )

    # A support line only spans ordinary walking geometry, never an elevator gap.
    if not pieces:
        return [
            dict(
                instruction="Arrive at the destination on the mapped path.",
                maneuver="arrive",
                distance_m=0,
                at=endpoint,
                geometry=[endpoint, endpoint],
                grade_pct=None,
            )
        ]
    runs = {}
    run_start = 0
    for index in range(len(pieces) + 1):
        boundary = index == len(pieces) or (
            index > run_start
            and (
                pieces[index]["kind"] != pieces[index - 1]["kind"]
                or math.dist(pieces[index - 1]["b"], pieces[index]["a"]) > 0.05
            )
        )
        if not boundary:
            continue
        points = [pieces[run_start]["a"], *(p["b"] for p in pieces[run_start:index])]
        line = LineString(points)
        offset = 0.0
        for k in range(run_start, index):
            runs[k] = line, offset
            offset += math.dist(pieces[k]["a"], pieces[k]["b"])
        run_start = index

    groups = []
    for index, piece in enumerate(pieces):
        code = None
        if index and piece["kind"] != "elevator" and pieces[index - 1]["kind"] == piece["kind"]:
            before = pieces[index - 1]
            if math.dist(before["b"], piece["a"]) < 0.05:
                incoming = (before["b"][0] - before["a"][0], before["b"][1] - before["a"][1])
                outgoing = (piece["b"][0] - piece["a"][0], piece["b"][1] - piece["a"][1])
                raw = angle(incoming, outgoing)
                line, position = runs[index]
                a = line.interpolate(max(0, position - 4))
                b = line.interpolate(min(line.length, position + 4))
                support = angle(
                    (piece["a"][0] - a.x, piece["a"][1] - a.y),
                    (b.x - piece["a"][0], b.y - piece["a"][1]),
                )
                if abs(raw) >= 30 and abs(support) >= 25 and raw * support > 0:
                    code = turn_code(raw)
        same = (
            groups
            and (groups[-1]["kind"], groups[-1]["name"]) == (piece["kind"], piece["name"])
            and math.dist(pieces[index - 1]["b"], piece["a"]) < 0.05
        )
        if same and not code:
            group = groups[-1]
            group["length"] += piece["length"]
            group["points"].append(piece["b"])
            group["grades"].append(piece["grade"])
        else:
            groups.append(
                dict(piece, code=code, points=[piece["a"], piece["b"]], grades=[piece["grade"]])
            )

    result = []
    for index, group in enumerate(groups):
        code = group["code"] or ("depart" if index == 0 else "straight")
        kind, name, distance = group["kind"], group["name"], group["length"]
        if kind == "elevator":
            code, text = "elevator", "Use the mapped elevator connection."
        elif kind == "steps":
            code, text = "stairs", f"Take the mapped stairs along {name} for {distance:.0f} m."
        elif kind == "ramp" and not group["code"]:
            code, text = "ramp", f"Follow the mapped ramp along {name} for {distance:.0f} m."
        elif group["code"]:
            action = {
                "left": "Turn left",
                "right": "Turn right",
                "slight-left": "Bear left",
                "slight-right": "Bear right",
                "sharp-left": "Turn sharply left",
                "sharp-right": "Turn sharply right",
                "u-turn": "Turn back",
            }[code]
            text = f"{action} onto {name}, then continue {distance:.0f} m."
        elif index == 0:
            a, b = group["points"][:2]
            bearing = math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360
            heading = (
                "north",
                "northeast",
                "east",
                "southeast",
                "south",
                "southwest",
                "west",
                "northwest",
            )[int((bearing + 22.5) // 45) % 8]
            text = f"Head {heading} along {name} for {distance:.0f} m."
        else:
            text = f"Continue onto {name} for {distance:.0f} m."
        result.append(
            dict(
                instruction=text,
                maneuver=code,
                distance_m=round(distance, 2),
                at=to_lnglat(*group["a"]),
                geometry=[to_lnglat(*point) for point in group["points"]],
                grade_pct=None if None in group["grades"] else max(group["grades"]),
            )
        )
    result.append(
        dict(
            instruction="Arrive at the destination on the mapped path.",
            maneuver="arrive",
            distance_m=0,
            at=endpoint,
            geometry=[endpoint, endpoint],
            grade_pct=None,
        )
    )
    return result
