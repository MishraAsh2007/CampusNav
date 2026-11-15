"""Render Ash's detailed backgrounds, in the same frame as the current ILC routes.

This exports display assets only. Ash's routing engine is not mounted or used to
compute current journeys. Image fingerprints must match the reviewed mosaics.
"""

import json
from copy import deepcopy
from html import escape
from pathlib import Path

from routing.app.indoor import router, schematic
from scripts.ash_ilc_additions import CORRECTED, sources

ROOT = Path(__file__).resolve().parents[1]

# Text/badge placement only, in source pixels. Room boundaries and routing nodes
# never move to make space for a label. Offset badges point to the traced shaft.
LABEL_LAYOUTS = {
    "1": {
        "rooms": {
            "ilc-f1-n140": {"at": [433, 540], "subtitle_lines": ["Commons", "Café"]},
            "ilc-f1-n151": {"at": [598, 565]},
            "ilc-f1-n155": {"at": [592, 405]},
            "ilc-f1-s112": {"at": [1018, 866], "size": 12},
            "ilc-f1-s122": {"at": [848, 884], "size": 12},
            "ilc-f1-s140": {"at": [703, 972]},
            "ilc-f1-restrooms": {"at": [701, 771], "size": 12},
        },
        "elevators": {
            "ilc-elev-north-f1": {"at": [516, 381], "anchor": [526, 412]},
            "ilc-elev-west-f1": {"at": [780, 827], "anchor": [727, 825]},
            "ilc-elev-east-f1": {"at": [1157, 816], "anchor": [1110, 839]},
        },
        "zones": {
            "Open foyer": {"hide_label": True},
            "S142": {"size": 10},
            "Service rooms": {"text": "Service", "subtitle": "rooms", "size": 9},
        },
    },
    "2": {
        "rooms": {
            "ilc-f2-n255": {"at": [593, 413]},
            "ilc-f2-s240": {"at": [777, 946]},
            "ilc-f2-s211": {"at": [990, 744]},
            "ilc-f2-s275": {"at": [759, 749], "size": 16},
            "ilc-f2-restrooms": {"at": [679, 761], "size": 12},
        },
        "elevators": {
            "ilc-elev-north-f2": {"at": [516, 379], "anchor": [527, 410]},
            "ilc-elev-west-f2": {"at": [780, 825], "anchor": [723, 824]},
            "ilc-elev-east-f2": {"at": [1158, 818], "anchor": [1110, 843]},
        },
        "doors": {
            "ilc-se": {"at": [1117, 935]},
            "ilc-nw": {"at": [412, 421]},
        },
        "zones": {
            "N151 auditorium": {"at": [588, 582], "size": 17},
            "S242": {"size": 9}, "S241A": {"size": 9},
            "Service rooms": {"text": "Service", "subtitle": "rooms", "size": 9},
        },
    },
}


def build():
    sources()  # Assert both original plan fingerprints before rendering.
    raw = json.loads((ROOT / "data/indoor/ilc.json").read_text(encoding="utf-8"))
    model = router.build_model("ilc", raw, [], False, None)
    for node in model.nodes.values():
        node["label"] = node["label"].replace("caf\u00c3\u00a9", "caf\u00e9")
    for ident, (_, label) in CORRECTED.items():
        model.nodes[ident]["label"] = f"ILC {label.split()[0]}"
    model.nodes["ilc-f1-n151"]["label"] = "ILC N151 (auditorium)"
    output = ROOT / "data/plan_wayfinding/sources/ilc"
    display = json.loads((output / "display-trace.json").read_text(encoding="utf-8"))
    plan = json.loads((ROOT / "data/plan_wayfinding/ilc.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in plan["nodes"]}
    for floor in ("1", "2"):
        floor_display = display["floors"][floor]
        entrance = floor_display["entrance"]
        entrance_id = "ilc-north-floor1" if floor == "1" else "ilc-sw"
        model.nodes[entrance_id].update(x=entrance["x"], y=entrance["y"])
        layout = deepcopy(LABEL_LAYOUTS[floor])
        layout.setdefault("doors", {})[entrance_id] = {
            "at": entrance["label"], "text": entrance["text"],
        }
        restrooms = next(zone for zone in floor_display["zones"]
                         if zone["label"] == "Restrooms")
        room_shapes = {f"ilc-f{floor}-restrooms": {
            "polygon": [[float(v) for v in point.split(",")]
                        for point in restrooms["points"].split()],
        }}
        zones = [zone for zone in floor_display["zones"] if zone["label"] != "Restrooms"]
        # The Simple map includes display landmarks without a routing node.
        # Render those too, and replace old box fallbacks with traced walls.
        named = {schematic._names(n["label"])[0]: ident
                 for ident, n in model.nodes.items()
                 if n["floor_id"] == floor and n["kind"] == "room"}
        for name, points, at in floor_display["rooms"]:
            if name in named:
                room_shapes[named[name]] = {
                    "polygon": [[float(v) for v in p.split(",")] for p in points.split()]}
            else:
                zones.append({"label": name, "points": points,
                              "at": list(map(float, at.split(","))),
                              "kind": "room"})
        circulation = []
        for edge in plan["connections"]:
            a, b = nodes[edge["start"]], nodes[edge["end"]]
            if edge["kind"] != "corridor" or a["floor_id"] != floor or b["floor_id"] != floor:
                continue
            circulation.append({"points": [a["x"], a["y"], b["x"], b["y"]],
                                "doorway": "room" in (a["kind"], b["kind"])})
        svg = schematic.render(model, floor, display_zones=zones,
                               display_layout=layout, circulation=circulation,
                               room_shapes=room_shapes)
        if not svg:
            raise ValueError(f"Missing detailed ILC floor {floor}")
        # Keep all four shaft symbols visible, even where a badge groups cars 1/2.
        details = ['<g aria-label="Elevator shafts and entrance reference">']
        for lift in floor_display["lifts"]:
            x, y = lift["x"], lift["y"]
            details.append(f'<g data-shaft="{escape(lift["id"])}">')
            details.append(f'<rect x="{x - 5}" y="{y - 6}" width="10" height="12" '
                           'rx="2" fill="#6d4fd6" stroke="white" stroke-width="1"/>')
            details.append(f'<path d="M{x - 2},{y - 1} l2,-3 2,3 M{x - 2},{y + 1} l2,3 2,-3" '
                           'fill="white" stroke="white" stroke-width="0.5"/>')
            details.append('</g>')
        legend = "1–2 Central elevators · 3 East elevator · 4 North elevator"
        details.append(f'<text x="755" y="1070" text-anchor="middle" '
                       f'font-family="{schematic.FONT}" font-size="12" fill="#6d4fd6">'
                       f'{escape(legend)}</text>')
        x, y = entrance["x"], entrance["y"]
        lx, ly = entrance["label"]
        details.append(f'<path d="M{lx},{ly + 7} L{x},{y}" fill="none" '
                       'stroke="#16834c" stroke-width="1"/>')
        # Name the exact threshold used by our source-plan guide. Other doors
        # remain in Ash's display, without adding automatic routing joins.
        details.append(f'<title>{escape(entrance["text"])}: {escape(entrance["floor"])}</title>')
        details.append('</g>')
        svg = svg.replace('</svg>', '\n'.join(details) + '\n</svg>')
        (output / f"detailed-{floor}.svg").write_text(svg + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    build()
    print("Rendered Ash detailed maps for ILC floors 1-2")
