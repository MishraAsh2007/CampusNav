"""Download the OSM walking network, classify and slim edges, add elevation, save to disk."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import osmnx as ox

from .. import config
from . import elevation as elevation_mod
from . import overrides as overrides_mod


def _first(value) -> Optional[str]:
    """OSM tags may be lists after simplification; take the first meaningful value."""
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if v), None)
    return None if value in (None, "") else str(value)


def classify_edge(data: dict) -> str:
    """steps | elevator | ramp | crossing | path."""
    highways = data.get("highway")
    highways = highways if isinstance(highways, (list, tuple)) else [highways]
    if "steps" in highways:
        return "steps"
    if "elevator" in highways:
        return "elevator"
    ramp = str(_first(data.get("ramp")) or "").lower()
    if ramp in ("yes", "true", "wheelchair"):
        return "ramp"
    footway = data.get("footway")
    footway = footway if isinstance(footway, (list, tuple)) else [footway]
    if "crossing" in footway:
        return "crossing"
    return "path"


def _slim_edges(G) -> None:
    """Keep only attributes the router needs (smaller graphml, no list-valued attrs)."""
    for _u, _v, _k, data in G.edges(keys=True, data=True):
        kind = classify_edge(data)
        steps = data.get("step_count")
        steps = _first(steps)
        slim = {
            "osmid": _first(data.get("osmid")) or "",
            "name": _first(data.get("name")) or "",
            "highway": _first(data.get("highway")) or "",
            "kind": kind,
            "length": float(data.get("length") or 0.0),
        }
        if steps and str(steps).isdigit():
            slim["step_count"] = int(steps)
        if "geometry" in data:
            slim["geometry"] = data["geometry"]
        data.clear()
        data.update(slim)


def _slim_nodes(G) -> None:
    for _n, data in G.nodes(data=True):
        keep = {k: data[k] for k in ("x", "y") if k in data}
        data.clear()
        data.update(keep)


def build_graph(
    bbox: Optional[dict] = None,
    out_path: Path = config.GRAPH_PATH,
    with_elevation: bool = True,
    ground_truth_path: Path = config.GROUND_TRUTH_PATH,
):
    """Build the cached campus graph. Needs internet (OSM + elevation API) unless cached."""
    b = bbox or config.BBOX
    print(f"[build] downloading OSM walk network for bbox {b}")
    # osmnx >= 2: bbox is (left, bottom, right, top)
    G = ox.graph_from_bbox(
        (b["west"], b["south"], b["east"], b["north"]),
        network_type="walk",
        simplify=True,
        retain_all=False,
    )
    G = ox.truncate.largest_component(G, strongly=False) if len(G) else G
    _slim_nodes(G)
    _slim_edges(G)

    if with_elevation:
        elevation_mod.add_elevation(G)
    else:
        print("[build] skipping elevation; all grades = 0")
        for n in G.nodes:
            G.nodes[n]["elevation"] = 0.0
        elevation_mod.compute_edge_grades(G)

    overrides_mod.apply_ground_truth(G, ground_truth_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, out_path)
    kinds: dict[str, int] = {}
    for _u, _v, d in G.edges(data=True):
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    print(f"[build] saved {out_path} | nodes={G.number_of_nodes()} edges={G.number_of_edges()} kinds={kinds}")
    return G
