"""Render Ash's detailed backgrounds, in the same frame as the current ILC routes.

This exports display assets only. Ash's routing engine is not mounted or used to
compute current journeys. Image fingerprints must match the reviewed mosaics.
"""

import json
from pathlib import Path

from routing.app.indoor import router, schematic
from scripts.ash_ilc_additions import CORRECTED, sources

ROOT = Path(__file__).resolve().parents[1]

# Text/badge placement only, in source pixels. Room boundaries and routing nodes
# never move to make space for a label. Offset badges point to the traced shaft.
LABEL_LAYOUTS = {
    "1": {
        "rooms": {
            "ilc-f1-n140": {"at": [445, 540], "subtitle": "Commons / café"},
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
        "zones": {"N151 auditorium": {"at": [588, 582], "size": 17}},
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
        restrooms = next(zone for zone in display["floors"][floor]["zones"]
                         if zone["label"] == "Restrooms")
        room_shapes = {f"ilc-f{floor}-restrooms": {
            "polygon": [[float(v) for v in point.split(",")]
                        for point in restrooms["points"].split()],
        }}
        zones = [zone for zone in display["floors"][floor]["zones"]
                 if zone["kind"] == "auditorium"]
        circulation = []
        for edge in plan["connections"]:
            a, b = nodes[edge["start"]], nodes[edge["end"]]
            if edge["kind"] != "corridor" or a["floor_id"] != floor or b["floor_id"] != floor:
                continue
            circulation.append({"points": [a["x"], a["y"], b["x"], b["y"]],
                                "doorway": "room" in (a["kind"], b["kind"])})
        svg = schematic.render(model, floor, display_zones=zones,
                               display_layout=LABEL_LAYOUTS[floor], circulation=circulation,
                               room_shapes=room_shapes)
        if not svg:
            raise ValueError(f"Missing detailed ILC floor {floor}")
        (output / f"detailed-{floor}.svg").write_text(svg + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    build()
    print("Rendered Ash detailed maps for ILC floors 1-2")
