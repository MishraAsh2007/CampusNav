"""Trace a building's footprint from a stitched floor-plan PNG, for the clean schematic plans.

    python scripts/plan_outline.py ilc 1 2            # building footprint
    python scripts/plan_outline.py --rooms ilc 1 2    # room shapes for the traced rooms

Reads data/plans/<building>/<floor>.png and writes data/plans/<building>/<floor>.outline.json:
{"polygons": [[[x, y], ...]], ...} in the PNG's pixel frame (the same frame the traced floors use).
With --rooms it writes <floor>.rooms.json: {node_id: {"polygon": [...], "method": "plan" | "box"}}.

Room shapes: the plan's black lines are its walls (seating, furniture and glass are drawn in color and
ignored). Walls are thickened to close door gaps, then each room is flood-filled from its label
(`label_at` in indoor_overrides.json). A fill that leaks (too big, or reaching the image edge) falls back
to a box around the label. Rooms marked "shape": "open" (the commons) get no shape; "box_px": [w, h] sizes a fallback box.

How: dark pixels are the plan's lines. They are thickened until the dashed outer walls close, the
outside is flood-filled from the image border, and what isn't outside is the building. That is shrunk
back, smoothed, traced (marching squares) and simplified (Ramer-Douglas-Peucker).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PLANS = Path(__file__).resolve().parents[1] / "data" / "plans"
CLOSE_PX = 17          # thickening that closes dashed walls (odd)
GRID = 3               # trace on a grid this coarse (px)
SIMPLIFY_PX = 4.0      # RDP tolerance (px)
MIN_AREA_FRAC = 0.03   # keep parts at least this share of the largest


def footprint(png: Path) -> Image.Image:
    gray = Image.open(png).convert("L")
    ink = gray.point(lambda v: 255 if v < 215 else 0)
    thick = ink.filter(ImageFilter.MaxFilter(CLOSE_PX))
    ImageDraw.floodfill(thick, (0, 0), 128)
    building = thick.point(lambda v: 0 if v == 128 else 255)
    building = building.filter(ImageFilter.MinFilter(CLOSE_PX - 4))
    return building.filter(ImageFilter.GaussianBlur(2)).point(lambda v: 255 if v >= 128 else 0)


def components(grid: list[list[bool]]):
    h, w = len(grid), len(grid[0])
    seen = [[False] * w for _ in range(h)]
    out = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] and not seen[y][x]:
                stack, cells = [(x, y)], []
                seen[y][x] = True
                while stack:
                    cx, cy = stack.pop()
                    cells.append((cx, cy))
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                out.append(cells)
    return out


def loops(grid: list[list[bool]]) -> list[list[tuple[float, float]]]:
    """Marching squares: closed boundary loops of the True region, in grid units (cell corners)."""
    h, w = len(grid), len(grid[0])
    at = lambda x, y: 0 <= x < w and 0 <= y < h and grid[y][x]
    nxt: dict[tuple[float, float], tuple[float, float]] = {}
    # Each foreground cell edge that borders background becomes a directed edge (region on the right).
    for y in range(h):
        for x in range(w):
            if not grid[y][x]:
                continue
            if not at(x, y - 1):
                nxt[(x, y)] = (x + 1, y)
            if not at(x + 1, y):
                nxt[(x + 1, y)] = (x + 1, y + 1) if (x + 1, y) not in nxt else nxt[(x + 1, y)]
                nxt.setdefault((x + 1, y), (x + 1, y + 1))
            if not at(x, y + 1):
                nxt.setdefault((x + 1, y + 1), (x, y + 1))
            if not at(x - 1, y):
                nxt.setdefault((x, y + 1), (x, y))
    out, used = [], set()
    for s0 in list(nxt):
        if s0 in used:
            continue
        ring, cur = [], s0
        while cur not in used and cur in nxt:
            used.add(cur)
            ring.append(cur)
            cur = nxt[cur]
        if len(ring) > 8:
            out.append(ring)
    return out


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    norm = math.hypot(x2 - x1, y2 - y1) or 1e-9
    i, dmax = 0, 0.0
    for k in range(1, len(pts) - 1):
        x0, y0 = pts[k]
        d = abs((x2 - x1) * (y1 - y0) - (x1 - x0) * (y2 - y1)) / norm
        if d > dmax:
            i, dmax = k, d
    if dmax <= eps:
        return [pts[0], pts[-1]]
    return rdp(pts[: i + 1], eps)[:-1] + rdp(pts[i:], eps)


def outline(png: Path) -> dict:
    fp = footprint(png)
    w, h = fp.size
    small = fp.resize((w // GRID, h // GRID), Image.NEAREST)
    px = small.load()
    grid = [[px[x, y] > 0 for x in range(small.width)] for y in range(small.height)]
    rings = sorted(loops(grid), key=len, reverse=True)
    if not rings:
        return {"polygons": []}
    polys = []
    for r in rings:
        if len(r) < MIN_AREA_FRAC * len(rings[0]):
            continue
        ring = [(x * GRID, y * GRID) for x, y in r]
        # RDP needs distinct endpoints: split the closed ring at the point farthest from its start.
        far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
        ring = rdp(ring[: far + 1], SIMPLIFY_PX)[:-1] + rdp(ring[far:] + [ring[0]], SIMPLIFY_PX)
        polys.append([[round(x, 1), round(y, 1)] for x, y in ring])
    return {"polygons": polys, "width": w, "height": h,
            "source": f"Traced from {png.name} by scripts/plan_outline.py (close {CLOSE_PX}px, grid {GRID}px)."}


OVERRIDES = PLANS.parent / "indoor_overrides.json"
WALL_CLOSE_PX = 9        # closes door gaps (~1 m) without merging rooms
ROOM_MAX_AREA = 70000    # px; bigger means the fill leaked into a hallway
ROOM_MIN_AREA = 2500     # px; smaller means it caught a closet or the gap between fixtures
BOX = (110, 70)          # fallback box around a label (px)


def _walls(png: Path) -> Image.Image:
    rgb = Image.open(png).convert("RGB")
    w, h = rgb.size
    src = rgb.load()
    mask = Image.new("L", (w, h), 0)
    dst = mask.load()
    for y in range(h):
        for x in range(w):
            r, g, b = src[x, y]
            dark = max(r, g, b) < 150 and max(r, g, b) - min(r, g, b) < 45   # walls: black / dark grey
            glass = b > 150 and r < 110 and g < 110                            # exterior glass: blue
            if dark or glass:
                dst[x, y] = 255
    return mask.filter(ImageFilter.MaxFilter(WALL_CLOSE_PX))


def _free_near(walls, x: int, y: int, r: int = 25):
    px = walls.load()
    for d in range(r):
        for dx in range(-d, d + 1):
            for dy in (-d, d) if abs(dx) != d else range(-d, d + 1):
                X, Y = x + dx, y + dy
                if 0 <= X < walls.width and 0 <= Y < walls.height and px[X, Y] == 0:
                    return X, Y
    return None


def room_shape(walls: Image.Image, x: float, y: float):
    start = _free_near(walls, int(x), int(y))
    if start is None:
        return None
    fill = walls.copy()
    ImageDraw.floodfill(fill, start, 128)
    region = fill.point(lambda v: 255 if v == 128 else 0)
    bbox = region.getbbox()
    area = region.histogram()[255]
    if not bbox or area > ROOM_MAX_AREA or area < ROOM_MIN_AREA or bbox[0] <= 1 or bbox[1] <= 1 \
            or bbox[2] >= walls.width - 1 or bbox[3] >= walls.height - 1:
        return None
    region = region.filter(ImageFilter.MaxFilter(WALL_CLOSE_PX - 2))  # back out to the wall line
    small = region.resize((region.width // 2, region.height // 2), Image.NEAREST)
    spx = small.load()
    grid = [[spx[i, j] > 0 for i in range(small.width)] for j in range(small.height)]
    rings = sorted(loops(grid), key=len, reverse=True)
    if not rings:
        return None
    ring = [(a * 2, b * 2) for a, b in rings[0]]
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
    ring = rdp(ring[: far + 1], 2.0)[:-1] + rdp(ring[far:] + [ring[0]], 2.0)
    return [[round(a, 1), round(b, 1)] for a, b in ring]


def rooms(building: str, floor: str) -> dict:
    spec = json.loads(OVERRIDES.read_text(encoding="utf-8"))["buildings"][building]["traced_floors"][floor]
    walls = _walls(PLANS / building / f"{floor}.png")
    out = {}
    for nid, n in spec["nodes"].items():
        if n.get("kind") != "room" or not n.get("label_at"):
            continue
        if n.get("shape") == "open":  # open areas (commons): label only
            continue
        lx, ly = n["label_at"]
        poly = room_shape(walls, lx, ly)
        if poly and len(poly) >= 4:
            out[nid] = {"polygon": poly, "method": "plan"}
        else:
            bw, bh = n.get("box_px") or BOX
            out[nid] = {"polygon": [[lx - bw / 2, ly - bh / 2], [lx + bw / 2, ly - bh / 2],
                                    [lx + bw / 2, ly + bh / 2], [lx - bw / 2, ly + bh / 2]], "method": "box"}
    return out


def main() -> int:
    args = sys.argv[1:]
    room_mode = "--rooms" in args
    args = [a for a in args if a != "--rooms"]
    if len(args) < 2:
        print(__doc__)
        return 1
    building, floors = args[0], args[1:]
    if room_mode:
        for f in floors:
            data = rooms(building, f)
            out = PLANS / building / f"{f}.rooms.json"
            out.write_text(json.dumps(data), encoding="utf-8")
            print(out, {k: v["method"] for k, v in data.items()})
        return 0
    for f in floors:
        png = PLANS / building / f"{f}.png"
        data = outline(png)
        out = PLANS / building / f"{f}.outline.json"
        out.write_text(json.dumps(data), encoding="utf-8")
        print(out, "polygons:", len(data["polygons"]), "points:", [len(p) for p in data["polygons"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
