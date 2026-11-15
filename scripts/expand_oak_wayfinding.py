"""Expand Oak's shared-hall wayfinding across all six documented floor references.

Room-associated endpoints are nearby hall landmarks, not surveyed door thresholds.
"""

import hashlib
import json
import re
from pathlib import Path

import pymupdf
from shapely.geometry import LineString, Point

from campus_notices.cache import atomic_json
from campus_notices.plan_integrity import require_reviewed_source
from campus_routing.plan_wayfinding import PlanWayfindingMap
from scripts.build_brown_trace import _source_url
from scripts.trace_oak_wayfinding import BANK, build

ROOT = Path(__file__).resolve().parents[1]
PLANS = {
    "1": "707-01.pdf",
    "2": "707-02.pdf",
    "3": "707-03.04.pdf",
    "4": "707-03.04.pdf",
    "5": "707-05.pdf",
    "6": "707-06.pdf",
}
HALLS = {
    "1": {"west": [(64, 273), (311, 314)], "east": [(443, 369), (729, 416)]},
    "2": {"main": [(66, 278), (358, 324), (351, 356), (729, 416)]},
    "3": {"main": [(64, 283), (360, 331), (350, 361), (730, 420)]},
    "4": {"main": [(64, 283), (360, 331), (350, 361), (730, 420)]},
    "5": {"main": [(339, 359), (733, 421)]},
    "6": {"main": [(105, 311), (715, 409)]},
}
STOPS = {"3": (370, 359), "4": (370, 359), "5": (370, 357), "6": (170, 303)}


def extend(base, records, sources):
    raw = base.model_dump(mode="json")
    raw["floor_sources"] = sources
    node_ids = {n["id"] for n in raw["nodes"]}
    counts = {}
    for floor, halls in HALLS.items():
        record = records[floor]
        with pymupdf.open(record["local_path"]) as doc:
            labels = []
            for x0, y0, x1, y1, text, *_ in doc[0].get_text("words"):
                if not (180 < y0 < 500):
                    continue
                if floor in ["3", "4"]:
                    if not re.fullmatch(r"-\d{2}", text):
                        continue
                    room = floor + text[1:]
                else:
                    if not re.fullmatch(floor + r"\d{2}", text):
                        continue
                    room = text
                labels.append((room, Point((x0 + x1) / 2, (y0 + y1) / 2)))
        seen = set()
        counts[floor] = 0
        for section, coords in halls.items():
            line = LineString(coords)
            stations = [(0, None), (line.length, None)]
            stations += [(line.project(Point(p)), None) for p in coords[1:-1]]
            for room, point in labels:
                if room in seen:
                    continue
                number = int(room[-2:])
                if floor == "1" and not (
                    (section == "west" and number >= 30) or (section == "east" and number <= 19)
                ):
                    continue
                if point.distance(line) > 65:
                    continue
                t = line.project(point)
                stations.append((t, "near-" + room))
                seen.add(room)
                counts[floor] += 1
            ordered = []
            for i, (t, ident) in enumerate(sorted(stations, key=lambda r: r[0])):
                p = line.interpolate(t)
                key = ident or f"oak-{floor}-{section}-bend-{i}"
                if key not in node_ids:
                    raw["nodes"].append(
                        dict(
                            id=key,
                            label=(
                                f"Shared hall near Room {key[5:]} (door position not surveyed)"
                                if ident
                                else f"Floor {floor} shared hall bend"
                            ),
                            floor_id=floor,
                            x=p.x,
                            y=p.y,
                        )
                    )
                    node_ids.add(key)
                ordered.append(key)
            for a, b in zip(ordered, ordered[1:], strict=False):
                raw["connections"].append(
                    dict(
                        id=a + "--" + b,
                        start=a,
                        end=b,
                        kind="corridor",
                        asset_id=f"oak-shared-hall-{floor}",
                        evidence="Shared corridor centerline "
                        "inspected on the floor-specific plan. Room text identifies a nearby "
                        "hall landmark, not an exact door; no private room interior is connected.",
                    )
                )
            if floor != "1":
                stop = "elevator-" + floor
                if stop not in node_ids:
                    x, y = STOPS[floor]
                    raw["nodes"].append(
                        dict(
                            id=stop,
                            label=f"Floor {floor} central elevator landing",
                            floor_id=floor,
                            x=x,
                            y=y,
                        )
                    )
                    node_ids.add(stop)
                nodes = {n["id"]: n for n in raw["nodes"]}
                anchor = min(
                    ordered,
                    key=lambda k: Point(nodes[k]["x"], nodes[k]["y"]).distance(
                        Point(nodes[stop]["x"], nodes[stop]["y"])
                    ),
                )
                raw["connections"].append(
                    dict(
                        id=stop + "--expanded-hall",
                        start=stop,
                        end=anchor,
                        kind="corridor",
                        asset_id=f"oak-shared-hall-{floor}",
                        evidence="Landing approach to the visible central bank on this floor plan; "
                        "operation, clearances and grade remain unknown.",
                    )
                )
        if floor in STOPS:
            lower = str(int(floor) - 1)
            raw["connections"].append(
                dict(
                    id=f"oak-elevator-{lower}-{floor}",
                    start="elevator-" + lower,
                    end="elevator-" + floor,
                    kind="elevator",
                    asset_id=BANK,
                    evidence="Corresponding central bank drawn on the specified floors.",
                    served_floor_evidence=f"Inspected central double-shaft bank on floor {lower} "
                    f"and {floor} drawings. Shared 3/4 source explicitly labels both floors. "
                    "This is documentary alignment; current served-floor operation is unconfirmed.",
                )
            )
    raw["source_warnings"] = [
        "Hall landmarks near room labels are not surveyed doorway positions.",
        "First-floor east/west wings are separate components: possible level changes "
        "near the lobby are not modeled as step-free links.",
        "Floors 3/4 share an explicitly labeled template. Private interiors are omitted.",
    ]
    raw["drawing_review"] = "Expanded six-floor shared-corridor drawing wayfinding. Floor-specific "
    raw["drawing_review"] += (
        "bank alignment reviewed in source drawings; no physical access verification."
    )
    return PlanWayfindingMap.model_validate(raw), counts


def main():
    manifest = json.loads((ROOT / "data/private/residence_floorplans/manifest.json").read_text())
    records = {}
    sources = {}
    for floor, name in PLANS.items():
        record = next(r for r in manifest["records"] if r["name"] == name)
        digest = hashlib.sha256(Path(record["local_path"]).read_bytes()).hexdigest()
        require_reviewed_source(name, digest)
        if digest != record["sha256"]:
            raise ValueError("Oak plan changed; re-inspect it")
        records[floor] = record
        sources[floor] = dict(url=_source_url(record["server_relative_url"]), sha256=digest)
    data, counts = extend(build(sources), records, sources)
    atomic_json(ROOT / "data/private/plan_wayfinding/oak.json", data.model_dump(mode="json"))
    atomic_json(
        ROOT / "data/private/plan_wayfinding/oak-coverage.json",
        dict(
            floor_hall_landmarks=counts,
            physical_verification=False,
            first_floor_wings_connected=False,
        ),
    )
    print(
        "Oak hall landmarks per floor:",
        counts,
        "nodes",
        len(data.nodes),
        "edges",
        len(data.connections),
    )


if __name__ == "__main__":
    main()
