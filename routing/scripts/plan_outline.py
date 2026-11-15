"""Trace a building's footprint from a stitched floor-plan PNG, for the clean schematic plans.

    python scripts/plan_outline.py ilc 1 2

Reads data/plans/<building>/<floor>.png and writes data/plans/<building>/<floor>.outline.json:
{"polygons": [[[x, y], ...]], ...} in the PNG's pixel frame (the same frame the traced floors use).

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


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    building, floors = sys.argv[1], sys.argv[2:]
    for f in floors:
        png = PLANS / building / f"{f}.png"
        data = outline(png)
        out = PLANS / building / f"{f}.outline.json"
        out.write_text(json.dumps(data), encoding="utf-8")
        print(out, "polygons:", len(data["polygons"]), "points:", [len(p) for p in data["polygons"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
