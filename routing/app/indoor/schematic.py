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

HALL_W = 10          # Display stroke only; not a measured corridor width.
STUB_W = 4           # Quiet doorway approach, below the selected route.
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


def render(model, floor_id: str, width: int = 1536, height: int = 1280,
           display_zones: list[dict] | None = None,
           display_layout: dict | None = None, circulation: list[dict] | None = None,
           room_shapes: dict | None = None) -> str | None:
    traced = ((model.ov.get("traced_floors") or {}).get(floor_id)) or None
    of = outline_file(model.key, floor_id)
    if not traced or of is None:
        return None
    polys = json.loads(of.read_text(encoding="utf-8")).get("polygons", [])
    nodes = {k: v for k, v in model.nodes.items() if v["floor_id"] == floor_id and v.get("x") is not None}
    layout = display_layout or {}
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs><filter id='sh' x='-5%' y='-5%' width='110%' height='110%'>"
        "<feDropShadow dx='0' dy='3' stdDeviation='6' flood-color='#1f2933' flood-opacity='0.12'/></filter></defs>",
    ]
    # footprint
    for poly in polys:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly)
        out.append(f'<polygon points="{pts}" fill="#fbfaf7" stroke="#7d8794" stroke-width="3" '
                   f'stroke-linejoin="round" filter="url(#sh)"/>')

    # rooms: shapes read off the plan (scripts/plan_outline.py --rooms), else none
    rf = config.INDOOR_PLANS_DIR / model.key / f"{floor_id}.rooms.json"
    if rf.is_file():
        shapes = json.loads(rf.read_text(encoding="utf-8"))
        shapes.update(room_shapes or {})
        for nid, r in shapes.items():
            if nid not in nodes:
                continue
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in r["polygon"])
            fill = "#eef3fa" if "restroom" in (nodes[nid].get("label") or "").lower() else "#ffffff"
            out.append(f'<polygon points="{pts}" fill="{fill}" stroke="#aeb7c2" stroke-width="3" stroke-linejoin="round"/>')

    # Source-traced display areas may span floors without having a routing node
    # on each floor (for example N151's upper auditorium level).
    zone_labels = []
    for zone in display_zones or []:
        out.append(f'<g data-display-zone="{escape(zone["label"], quote=True)}">')
        kind = zone.get("kind")
        fill = {"open": "#f0fdfa", "service": "#eef2f6", "room": "#ffffff"}.get(kind, "#eef3fa")
        stroke = 3 if kind in ("auditorium", "room") else 1.5
        border = "none" if kind == "open" else "#aeb7c2"
        out.append(f'<polygon points="{escape(zone["points"], quote=True)}" '
                   f'fill="{fill}" stroke="{border}" stroke-width="{stroke}" '
                   'stroke-linejoin="round"/>')
        label = layout.get("zones", {}).get(zone["label"], {})
        if label.get("hide_label"):
            out.append('</g>')
            continue
        x, y = label.get("at", zone["at"])
        size = label.get("size", 12 if kind in ("open", "service", "room") else 20)
        zone_labels.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-family="{FONT}" '
                   f'font-size="{size}" font-weight="650" '
                   f'fill="#34404d">{escape(label.get("text", zone["label"]))}</text>')
        subtitle = label.get("subtitle", zone.get("subtitle"))
        if subtitle:
            dy = 13 if kind == "service" else 22
            subsize = size if kind == "service" else 15
            zone_labels.append(f'<text x="{x}" y="{y + dy}" text-anchor="middle" '
                       f'font-family="{FONT}" '
                       f'font-size="{subsize}" fill="#5f6b78">{escape(subtitle)}</text>')
        out.append('</g>')

    # hallways: edges between non-room nodes; doorway stubs to rooms
    halls, stubs = [], []
    for a, b, data in model.G.edges(data=True):
        e = data.get("edge")
        if not e or e["kind"] == "elevator" or a not in nodes or b not in nodes:
            continue
        seg = (nodes[a]["x"], nodes[a]["y"], nodes[b]["x"], nodes[b]["y"])
        (stubs if "room" in (nodes[a]["kind"], nodes[b]["kind"]) else halls).append(seg)
    if circulation is not None:
        # The background and selected route must use the same routing edition.
        # These paths are a display layer; no graph coordinates are modified.
        halls = [edge["points"] for edge in circulation if not edge["doorway"]]
        stubs = [edge["points"] for edge in circulation if edge["doorway"]]
    for color, w, segs in (("#e4e9ee", HALL_W, halls), ("#e9edf1", STUB_W, stubs)):
        for x1, y1, x2, y2 in segs:
            out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}" '
                       f'stroke-linecap="round"/>')

    out.extend(zone_labels)
    # rooms: the name stays inside the room; destination dots belong to the route.
    spec_nodes = traced.get("nodes", {})
    for nid, n in nodes.items():
        if n["kind"] != "room":
            continue
        # Doorway dots repeat the route endpoints and crowd small rooms. The
        # selected destination remains marked by the frontend route overlay.
        lx, ly = (spec_nodes.get(nid, {}).get("label_at") or [n["x"], n["y"] - 18])
        label = layout.get("rooms", {}).get(nid, {})
        lx, ly = label.get("at", [lx, ly])
        size = label.get("size", 19)
        main, sub = _names(n.get("label") or nid)
        sub = label.get("subtitle", sub)
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-family="{FONT}" font-size="{size}" '
                   f'font-weight="650" fill="#34404d">{escape(main)}</text>')
        subtitles = label.get("subtitle_lines", [sub] if sub else [])
        for i, subtitle in enumerate(subtitles, start=1):
            out.append(f'<text x="{lx}" y="{ly + 17 * i}" text-anchor="middle" font-family="{FONT}" font-size="12" '
                       f'fill="#5f6b78">{escape(subtitle)}</text>')

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
        badge = layout.get("elevators", {}).get(nid, {})
        x, y = badge.get("at", [n["x"], n["y"]])
        anchor_x, anchor_y = badge.get("anchor", [n["x"], n["y"]])
        if abs(x - anchor_x) + abs(y - anchor_y) > 8:
            out.append(f'<path d="M{x},{y} L{anchor_x},{anchor_y}" '
                       'fill="none" stroke="#a78bfa" stroke-width="1.5"/>')
            out.append(f'<circle cx="{anchor_x}" cy="{anchor_y}" r="2.5" fill="#6d4fd6"/>')
        w = 24 + 16 * max(0, len(nums) - 1)
        out.append(f'<rect x="{x - w / 2}" y="{y - 12}" width="{w}" height="24" '
                   'rx="6" fill="#6d4fd6" stroke="white" stroke-width="1.5"/>')
        out.append(f'<text x="{x}" y="{y + 5}" text-anchor="middle" '
                   f'font-family="{FONT}" font-size="14" '
                   f'font-weight="700" fill="#ffffff">{escape(text)}</text>')

    # doors onto this floor
    for d in model.doors:
        n = nodes.get(d.node)
        if not n or n.get("x") is None:
            continue
        ok = d.step_free is not False
        color = "#1f9d55" if ok else "#9aa5b1"
        out.append(f'<circle cx="{n["x"]}" cy="{n["y"]}" r="7" fill="{color}" '
                   'stroke="#ffffff" stroke-width="2"/>')
        label = layout.get("doors", {}).get(d.node, {})
        lx, ly = label.get("at", [n["x"], n["y"] - 20])
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" '
                   f'font-family="{FONT}" font-size="12" '
                   f'font-weight="600" fill="{"#16794a" if ok else "#6b7682"}">'
                   f'{escape(label.get("text", _short_door(d.name)))}</text>')
    out.append("</svg>")
    return "\n".join(out)
