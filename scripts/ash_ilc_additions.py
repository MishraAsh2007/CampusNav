"""Reviewed Ash_ver additions in the existing ILC drawing/portal coordinate frame.

Only explicit paths listed below join the current pilot. No nearest-node joins,
placeholder floors, or pixel-to-meter distance estimates are imported.
"""

import hashlib
import json
from itertools import pairwise
from pathlib import Path

from campus_notices.plan_integrity import require_reviewed_source

ROOT = Path(__file__).resolve().parents[1]
ASH = ROOT / "routing/data"
DISPLAY = ROOT / "data/plan_wayfinding/sources/ilc/display-trace.json"


def sources():
    for floor in ("1", "2"):
        digest = hashlib.sha256((ASH / f"plans/ilc/{floor}.png").read_bytes()).hexdigest()
        require_reviewed_source(f"ilc-floor-{floor}.png", digest)
    return json.loads((ASH / "indoor_overrides.json").read_text(encoding="utf-8"))[
        "buildings"
    ]["ilc"]["traced_floors"]


# The source labels for these two rooms disagree with the printed floor-2 plan.
CORRECTED = {
    "ilc-f2-s211": ("ilc-door-s241-f2", "S241 hallway approach"),
    "ilc-f2-s275": ("ilc-door-s225-f2", "S225 hallway approach"),
}


def add_routes(nodes, connections):
    trace = sources()
    known = {n["id"]: n for n in nodes}
    source_nodes = {
        key: dict(value, floor_id=floor)
        for floor in ("1", "2")
        for key, value in trace[floor]["nodes"].items()
    }

    def include(key):
        if key in known:
            return key
        raw = source_nodes[key]
        ident, label = CORRECTED.get(key, (key, raw["label"]))
        # Repair the incoming UTF-8/Latin-1 mojibake in the cafe label.
        label = label.replace("caf\u00c3\u00a9", "caf\u00e9")
        if ident not in known:
            value = {k: raw[k] for k in ("x", "y", "kind", "floor_id")}
            value.update(id=ident, label=label)
            nodes.append(value)
            known[ident] = value
        return ident

    def link(a, b, **extra):
        connections.append(dict(
            id=f"ash-{a}--{b}", start=a, end=b, kind="corridor",
            asset_id=f"ash-{a}--{b}",
            evidence=("Ash_ver floor-plan trace, checked in the identical UMass mosaic "
                      "coordinate frame on 2026-11-15. Hallway approach; access unmeasured."),
            **extra,
        ))

    # Shared hall joins were checked against both source mosaics; IDs are not
    # matched by distance. Keep existing destination and southwest portal IDs.
    paths = [
        ["ilc-north-f1", "f1-lobby-n", "ilc-f1-n140"],
        ["ilc-south-junction-f1", "f1-s-mid", "ilc-f1-n101"],
        ["ilc-west-hall-f1", "f1-core-mid", "ilc-f1-restrooms"],
        ["ilc-south-hall-f1", "f1-main-3", "ilc-f1-s131"],
        ["ilc-south-hall-f1", "f1-main-s122", "f1-main-4", "f1-main-s112",
         "f1-main-5", "f1-main-e"],
        ["f1-main-s122", "ilc-f1-s122"],
        ["f1-main-s112", "ilc-f1-s112"],
        ["f1-main-5", "ilc-f1-s110"],
        ["ilc-sw-lobby-f2", "ilc-f2-n201"],
        ["ilc-west-hall-f2", "f2-core-mid", "ilc-f2-restrooms"],
        ["ilc-south-hall-f2", "f2-main-s275", "ilc-f2-s275"],
        ["ilc-south-hall-f2", "f2-main-b", "ilc-f2-s231"],
        ["ilc-east-hall-f2", "f2-main-d", "ilc-f2-s211"],
        ["ilc-east-hall-f2", "f2-main-e", "f2-lobby-se"],
    ]
    for path in paths:
        for a, b in pairwise(path):
            link(include(a), include(b))

    for floor in ("1", "2"):
        pos = trace[floor]["elevator_stops"][f"ilc-elev-east-f{floor}"]
        label = f"North Pleasant Street elevator beside S{'110' if floor == '1' else '220'}"
        ident = f"ilc-lift-east-f{floor}"
        nodes.append(dict(id=ident, label=label, floor_id=floor, kind="elevator_stop", **pos))
        link(f"f{floor}-main-e", ident)
    evidence = ("Matching east shaft on both UMass plans; Ash_ver on-site identification "
                "and user confirmation of four ILC elevators on 2026-11-15. "
                "Only floors 1-2 are enabled; current operation unverified.")
    connections.append(dict(
        id="ilc-lift-east-f1--ilc-lift-east-f2", start="ilc-lift-east-f1",
        end="ilc-lift-east-f2", kind="elevator", asset_id="ilc-lift-east",
        evidence=evidence, served_floor_evidence=evidence,
        forward_instruction=("Take the North Pleasant Street elevator beside S110 to floor 2. "
                             "Confirm the floor sign before continuing."),
        reverse_instruction=("Take the North Pleasant Street elevator beside S220 to floor 1. "
                             "Confirm the floor sign before continuing."),
    ))
    aliases = {
        "ilc-lift-east": ["ilc-elevator-east", "umass-elevator-187"],
        "ilc-lift-north": ["ilc-elevator-north"],
        "ilc-lift-central-q": ["ilc-elevator-core-a"],
        "ilc-lift-central-p": ["ilc-elevator-core-b"],
    }
    for edge in connections:
        if edge["asset_id"] in aliases:
            edge["asset_aliases"] = aliases[edge["asset_id"]]


def update_display_trace():
    trace = sources()
    display = json.loads(DISPLAY.read_text(encoding="utf-8"))
    for floor in ("1", "2"):
        plan = display["floors"][floor]
        rooms = json.loads((ASH / f"plans/ilc/{floor}.rooms.json").read_text())
        by_name = {room[0]: room for room in plan["rooms"]}
        for key, shape in rooms.items():
            if shape.get("method") != "plan":
                continue  # Ash's box fallbacks are not traced classroom walls.
            raw = trace[floor]["nodes"][key]
            name = CORRECTED[key][1].split()[0] if key in CORRECTED else raw["label"].split()[1]
            points = " ".join(f"{x},{y}" for x, y in shape["polygon"])
            at = ",".join(map(str, raw["label_at"]))
            if name in by_name:
                by_name[name][:] = [name, points, at]
            else:
                plan["rooms"].append([name, points, at])
        plan["lifts"] = [lift for lift in plan["lifts"] if lift["id"] != "east"]
        pos = trace[floor]["elevator_stops"][f"ilc-elev-east-f{floor}"]
        plan["lifts"].append(dict(id="east", **pos, source_symbol="crossed elevator-shaft box"))
        plan["trace_source"] = (
            "Ash_ver f73e8fc room polygons (method=plan only); current source hash retained."
        )
    DISPLAY.write_text(json.dumps(display, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
