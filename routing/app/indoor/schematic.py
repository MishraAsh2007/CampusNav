"""Clean SVG floor plans for traced floors: footprint, hallways, room names, elevators, doors.

Drawn in the same pixel frame as the floor's plan image (the traced floors' x, y), so the viewer can
use it as the floor's image and everything it draws on top (route, tap targets) still lines up.
The footprint comes from data/plans/<building>/<floor>.outline.json (scripts/plan_outline.py).
"""
from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Optional

from .. import config

HALL_W = 26          # main hallway band (px, ~2.9 m)
STUB_W = 12          # room doorway stub
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"


def outline_file(key: str, floor_id: str) -> Optional[Path]:
    p = config.INDOOR_PLANS_DIR / key / f"{floor_id}.outline.json"
    return p if p.is_file() else None


def _names(label: str) -> tuple[str, str]:
    """'ILC N140 (commons and café)' -> ('N140', 'Commons and café'); 'Restrooms, 1st Floor' -> ('Restrooms', '')."""
    label = re.sub(r"^ILC\s+", "", label)
    label = re.sub(r",\s*\d\w*\s+Floor$", "", label)
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", label)
    if m:
        sub = m.group(2)
        return m.group(1), sub[:1].upper() + sub[1:]
    return label, ""


def _short_door(name: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", name)


def render(model, floor_id: str, width: int = 1536, height: int = 1280) -> Optional[str]:
    traced = ((model.ov.get("traced_floors") or {}).get(floor_id)) or None
    of = outline_file(model.key, floor_id)
    if not traced or of is None:
        return None
    polys = json.loads(of.read_text(encoding="utf-8")).get("polygons", [])
    nodes = {k: v for k, v in model.nodes.items() if v["floor_id"] == floor_id and v.get("x") is not None}
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs><filter id='sh' x='-5%' y='-5%' width='110%' height='110%'>"
        "<feDropShadow dx='0' dy='3' stdDeviation='6' flood-color='#1f2933' flood-opacity='0.12'/></filter></defs>",
    ]
    # footprint
    for poly in polys:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly)
        out.append(f'<polygon points="{pts}" fill="#fbfaf7" stroke="#7d8794" stroke-width="5" '
                   f'stroke-linejoin="round" filter="url(#sh)"/>')

    # rooms: shapes read off the plan (scripts/plan_outline.py --rooms), else none
    rf = config.INDOOR_PLANS_DIR / model.key / f"{floor_id}.rooms.json"
    if rf.is_file():
        for nid, r in json.loads(rf.read_text(encoding="utf-8")).items():
            if nid not in nodes:
                continue
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in r["polygon"])
            fill = "#eef3fa" if "restroom" in (nodes[nid].get("label") or "").lower() else "#ffffff"
            out.append(f'<polygon points="{pts}" fill="{fill}" stroke="#aeb7c2" stroke-width="3" stroke-linejoin="round"/>')

    # hallways: edges between non-room nodes; doorway stubs to rooms
    halls, stubs = [], []
    for a, b, data in model.G.edges(data=True):
        e = data.get("edge")
        if not e or e["kind"] == "elevator" or a not in nodes or b not in nodes:
            continue
        seg = (nodes[a]["x"], nodes[a]["y"], nodes[b]["x"], nodes[b]["y"])
        (stubs if "room" in (nodes[a]["kind"], nodes[b]["kind"]) else halls).append(seg)
    for color, w, segs in (("#dfe5ec", HALL_W, halls), ("#e8ecf1", STUB_W, stubs)):
        for x1, y1, x2, y2 in segs:
            out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}" '
                       f'stroke-linecap="round"/>')

    # rooms: a dot at the door, the name at the room
    spec_nodes = traced.get("nodes", {})
    for nid, n in nodes.items():
        if n["kind"] != "room":
            continue
        out.append(f'<circle cx="{n["x"]}" cy="{n["y"]}" r="5" fill="#9aa5b1"/>')
        lx, ly = (spec_nodes.get(nid, {}).get("label_at") or [n["x"], n["y"] - 18])
        main, sub = _names(n.get("label") or nid)
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-family="{FONT}" font-size="22" '
                   f'font-weight="650" fill="#34404d">{escape(main)}</text>')
        if sub:
            out.append(f'<text x="{lx}" y="{ly + 20}" text-anchor="middle" font-family="{FONT}" font-size="15" '
                       f'fill="#5f6b78">{escape(sub)}</text>')

    # elevators: a purple tile per stop, numbered by car
    ev = model.ov.get("elevators") or {}
    numbers = {c["id"]: c.get("number") for c in ev.get("cars", [])}
    banks = {k: v.get("cars", []) for k, v in (ev.get("banks") or {}).items()}
    stop_asset = {}
    for a, b, data in model.G.edges(data=True):
        e = data.get("edge")
        if e and e["kind"] == "elevator":
            for x in (a, b):
                stop_asset[x] = e.get("asset_id")
    for nid, n in nodes.items():
        if n["kind"] != "elevator_stop":
            continue
        nums = [str(numbers[c]) for c in banks.get(stop_asset.get(nid), []) if numbers.get(c)]
        text = " ".join(nums) if nums else "E"
        w = 34 + 22 * max(0, len(nums) - 1)
        out.append(f'<rect x="{n["x"] - w / 2}" y="{n["y"] - 17}" width="{w}" height="34" rx="9" fill="#6d4fd6"/>')
        out.append(f'<text x="{n["x"]}" y="{n["y"] + 7}" text-anchor="middle" font-family="{FONT}" font-size="19" '
                   f'font-weight="700" fill="#ffffff">{escape(text)}</text>')

    # doors onto this floor
    for d in model.doors:
        n = nodes.get(d.node)
        if not n or n.get("x") is None:
            continue
        ok = d.step_free is not False
        color = "#1f9d55" if ok else "#9aa5b1"
        out.append(f'<circle cx="{n["x"]}" cy="{n["y"]}" r="11" fill="{color}" stroke="#ffffff" stroke-width="3"/>')
        out.append(f'<text x="{n["x"]}" y="{n["y"] - 18}" text-anchor="middle" font-family="{FONT}" font-size="15" '
                   f'font-weight="600" fill="{"#16794a" if ok else "#6b7682"}">{escape(_short_door(d.name))}</text>')
    out.append("</svg>")
    return "\n".join(out)
