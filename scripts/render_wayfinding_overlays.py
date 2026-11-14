"""Create private SVG review overlays from the existing plans and graph coordinates."""

import base64
import html
import json
from pathlib import Path

from campus_routing.plan_wayfinding import PlanWayfindingMap
from scripts.expand_oak_wayfinding import PLANS

ROOT = Path(__file__).resolve().parents[1]


def render(data, backgrounds, folder):
    nodes = {n.id: n for n in data.nodes}
    for floor, (path, width, height) in backgrounds.items():
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode()
        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
            f'<image width="{width}" height="{height}" href="data:{mime};base64,{encoded}"/>',
        ]
        for e in data.connections:
            a, b = nodes[e.start], nodes[e.end]
            if (a.floor_id or data.floor_id) == (b.floor_id or data.floor_id) == floor:
                svg.append(
                    f'<polyline points="{a.x},{a.y} {b.x},{b.y}" fill="none" '
                    'stroke="#c00060" stroke-width="1.2"/>'
                )
        for n in data.nodes:
            if (n.floor_id or data.floor_id) == floor:
                svg.append(
                    f'<circle cx="{n.x}" cy="{n.y}" r="1.5" fill="#006ea6">'
                    f"<title>{html.escape(n.label)} [{n.id}]</title></circle>"
                )
        svg.append(
            '<text x="8" y="12" font-size="8" fill="#c00060">'
            "DRAWING WAYFINDING: shared-space landmarks; physical access unverified.</text></svg>"
        )
        (folder / f"{data.building_id}-floor-{floor}.svg").write_text(
            "\n".join(svg), encoding="utf-8"
        )


def main():
    folder = ROOT / "data/private/plan_wayfinding"
    inventory = json.loads((ROOT / "data/private/residence_floorplans/manifest.json").read_text())
    oak = PlanWayfindingMap.model_validate_json((folder / "oak.json").read_text())
    backgrounds = {}
    for floor, name in PLANS.items():
        row = next(r for r in inventory["records"] if r["name"] == name)
        backgrounds[floor] = (Path(row["trace"]["rendered_path"]), 792, 612)
    render(oak, backgrounds, folder)
    cc = PlanWayfindingMap.model_validate_json((folder / "campus-center.json").read_text())
    rows = json.loads((ROOT / ".cache/central-plans/image-manifest.json").read_text())["records"]
    by_url = {r["url"]: r for r in rows}
    backgrounds = {
        f: (Path(by_url[s["url"]]["local_path"]), int(s["width"]), int(s["height"]))
        for f, s in cc.floor_sources.items()
    }
    render(cc, backgrounds, folder)
    print("Rendered Oak and Campus Center floor overlays in", folder)


if __name__ == "__main__":
    main()
