"""Apply ground-truth (teammate-verified) data on top of OSM: elevators, ramps, entrances.

data/ground_truth.json schema (all sections optional):

{
  "links": [      # new connections OSM doesn't have (elevators, ramps, accessible shortcuts)
    {"id": "cc-elevator", "name": "Campus Center elevator", "kind": "elevator",
     "from": {"lat": ..., "lon": ...}, "to": {"lat": ..., "lon": ...},
     "length_m": 15, "grade_pct": 0, "photo": "photos/cc-elev.jpg", "notes": "..."}
  ],
  "edge_tags": [  # fix up existing OSM edges near a point
    {"id": "stairs-ilc", "lat": ..., "lon": ..., "radius_m": 8,
     "set": {"kind": "steps", "accessible": false, "grade_pct": 12, "step_count": 14}}
  ],
  "entrances": [  # recorded on the nearest node (for the frontend / Gemini descriptions)
    {"id": "ilc-main", "name": "ILC main entrance", "lat": ..., "lon": ..., "accessible": true,
     "photo": "photos/ilc.jpg", "notes": "automatic door, flush threshold"}
  ]
}
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Optional

from .. import config
from ..utils.geo import haversine_m, invalidate_node_index, nearest_node, node_latlon, point_to_polyline_m, edge_coords

SNAP_TOLERANCE_M = 12.0
VALID_KINDS = {"path", "steps", "ramp", "elevator", "crossing"}


def _snap_or_create(G, lat: float, lon: float, ref_id: str, slot: str) -> int:
    """Use an existing node within tolerance, otherwise create a new one."""
    if len(G):
        n, dist = nearest_node(G, lat, lon)
        if dist <= SNAP_TOLERANCE_M:
            return n
    new_id = -(zlib.crc32(f"{ref_id}:{slot}".encode()) % 900_000_000) - 1  # deterministic negative id
    while new_id in G:
        new_id -= 1
    elev = 0.0
    if len(G):
        n, _ = nearest_node(G, lat, lon)
        elev = G.nodes[n].get("elevation", 0.0)
    G.add_node(new_id, x=lon, y=lat, elevation=elev)
    invalidate_node_index(G)
    return new_id


def _add_links(G, links: list[dict]) -> int:
    added = 0
    for link in links:
        kind = link.get("kind", "path")
        if kind not in VALID_KINDS:
            raise ValueError(f"link {link.get('id')}: unknown kind {kind!r}")
        a = _snap_or_create(G, link["from"]["lat"], link["from"]["lon"], link["id"], "from")
        b = _snap_or_create(G, link["to"]["lat"], link["to"]["lon"], link["id"], "to")
        if a == b:
            continue
        length = float(link.get("length_m") or haversine_m(*node_latlon(G, a), *node_latlon(G, b)))
        if link.get("grade_pct") is not None:
            grade = float(link["grade_pct"])
        elif kind == "elevator":
            grade = 0.0
        else:
            grade = (G.nodes[b]["elevation"] - G.nodes[a]["elevation"]) / max(length, 0.1) * 100
        for u, v, g in ((a, b, grade), (b, a, -grade)):
            attrs = {
                "osmid": f"gt:{link['id']}",
                "name": link.get("name", ""),
                "highway": "elevator" if kind == "elevator" else "footway",
                "kind": kind,
                "length": length,
                "grade": round(g, 2),
                "grade_abs": round(abs(g), 2),
            }
            if link.get("accessible") is not None:
                attrs["accessible"] = bool(link["accessible"])
            G.add_edge(u, v, **attrs)
            added += 1
    return added


def _apply_edge_tags(G, tags: list[dict]) -> int:
    touched = 0
    for tag in tags:
        lat, lon, radius = tag["lat"], tag["lon"], float(tag.get("radius_m", 10))
        updates = dict(tag.get("set", {}))
        if updates.get("kind", "path") not in VALID_KINDS:
            raise ValueError(f"edge_tag {tag.get('id')}: unknown kind {updates['kind']!r}")
        for u, v, _k, data in G.edges(keys=True, data=True):
            if point_to_polyline_m(lat, lon, edge_coords(G, u, v, data)) > radius:
                continue
            for key, val in updates.items():
                if key == "grade_pct":
                    sign = -1 if (data.get("grade") or 0) < 0 else 1
                    data["grade"] = round(sign * float(val), 2)
                    data["grade_abs"] = round(abs(float(val)), 2)
                else:
                    data[key] = val
            touched += 1
    return touched


def _apply_entrances(G, entrances: list[dict]) -> int:
    for e in entrances:
        n, _ = nearest_node(G, e["lat"], e["lon"])
        G.nodes[n]["entrance"] = e.get("name", e["id"])
        G.nodes[n]["entrance_accessible"] = bool(e.get("accessible", True))
        if e.get("photo"):
            G.nodes[n]["entrance_photo"] = e["photo"]
        if e.get("notes"):
            G.nodes[n]["entrance_notes"] = e["notes"]
    return len(entrances)


def apply_ground_truth(G, path: Optional[Path] = config.GROUND_TRUTH_PATH) -> None:
    """Mutate G in place using the ground-truth JSON file (no-op if missing/empty)."""
    if path is None or not Path(path).exists():
        print("[overrides] no ground_truth.json; skipping")
        return
    gt = json.loads(Path(path).read_text(encoding="utf-8"))
    n_links = _add_links(G, gt.get("links", []))
    n_tags = _apply_edge_tags(G, gt.get("edge_tags", []))
    n_ent = _apply_entrances(G, gt.get("entrances", []))
    print(f"[overrides] links(edges)={n_links} edge_tags(edges)={n_tags} entrances={n_ent}")
