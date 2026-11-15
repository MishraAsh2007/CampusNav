"""Render Ash's detailed backgrounds, in the same frame as the current ILC routes.

This exports display assets only. Ash's routing engine is not mounted or used to
compute current journeys. Image fingerprints must match the reviewed mosaics.
"""

import json
from pathlib import Path

from routing.app.indoor import router, schematic
from scripts.ash_ilc_additions import CORRECTED, sources

ROOT = Path(__file__).resolve().parents[1]


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
    for floor in ("1", "2"):
        zones = [zone for zone in display["floors"][floor]["zones"]
                 if zone["kind"] == "auditorium"]
        svg = schematic.render(model, floor, display_zones=zones)
        if not svg:
            raise ValueError(f"Missing detailed ILC floor {floor}")
        (output / f"detailed-{floor}.svg").write_text(svg + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    build()
    print("Rendered Ash detailed maps for ILC floors 1-2")
