"""Load the cached graph at server startup and restore attribute types.

GraphML stores everything as strings, so numeric/boolean attributes are coerced
back here. This is the only place that knows about the on-disk format.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import osmnx as ox

from .. import config

_FLOAT_EDGE = ("length", "grade", "grade_abs")
_FLOAT_NODE = ("x", "y", "elevation")


def _to_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None  # empty / unknown


def _coerce(G) -> None:
    for _n, d in G.nodes(data=True):
        for k in _FLOAT_NODE:
            if k in d and d[k] not in ("", None):
                d[k] = float(d[k])
        if "entrance_accessible" in d:
            d["entrance_accessible"] = _to_bool(d["entrance_accessible"])

    for _u, _v, _k, d in G.edges(keys=True, data=True):
        for k in _FLOAT_EDGE:
            d[k] = float(d[k]) if d.get(k) not in ("", None) else 0.0
        if "accessible" in d:
            val = _to_bool(d["accessible"])
            if val is None:
                del d["accessible"]
            else:
                d["accessible"] = val
        if d.get("step_count") not in ("", None):
            d["step_count"] = int(float(d["step_count"]))
        else:
            d.pop("step_count", None)
        d["kind"] = d.get("kind") or "path"
        d["name"] = d.get("name") or None


def load_graph(path: Path = config.GRAPH_PATH):
    """Load graph.graphml (built by scripts/build_graph.py)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python scripts/build_graph.py` from routing/ first."
        )
    G = ox.load_graphml(path)
    _coerce(G)
    return G


_cache: dict[str, object] = {}


def get_graph(path: Path = config.GRAPH_PATH):
    """Process-wide cached graph."""
    key = str(path)
    if key not in _cache:
        _cache[key] = load_graph(path)
    return _cache[key]
