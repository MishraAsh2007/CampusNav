"""Snap start/end points to the graph without landing in a dead end.

Plain nearest-node snapping only looks at distance. A point well away from any path (a
building center, a GPS fix, a tap on the map) can land on a junction the user can't leave:
the only way out is stairs or a slope over their limit. The route then fails even though a
usable path runs a few meters farther away.

Rule: move a point only if ALL of these hold
  * it is at least SNAP_RESNAP_MIN_M from its nearest node (doors and points on a path keep
    their exact junction, so a truly inaccessible door still reports "no route"),
  * the start and end can't already reach each other (never changes a route that works),
  * its nearest node is outside the largest network the user can traverse,
  * a node in that network is within SNAP_MAX_EXTRA_M of the original snap distance.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Mapping, Optional

import networkx as nx
import numpy as np

from .. import config
from ..utils.geo import EARTH_RADIUS_M, _node_index, nearest_node
from .weights import EdgeKey, Prefs, best_parallel_edge

_CACHE: "OrderedDict[tuple, tuple[dict, int]]" = OrderedDict()
_CACHE_SIZE = 16


@dataclass
class Snap:
    node: int
    distance_m: float
    moved: bool = False
    original_node: Optional[int] = None
    original_distance_m: Optional[float] = None


def components(G, prefs: Prefs, blocked: Mapping[EdgeKey, object]) -> tuple[dict, int]:
    """(node -> strongly connected component id, id of the largest) for what ``prefs`` can use."""
    key = (id(G), prefs, frozenset(blocked))
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    H = nx.DiGraph()
    H.add_nodes_from(G.nodes)
    for u, v in G.edges():
        if not H.has_edge(u, v) and best_parallel_edge(G[u][v], u, v, prefs, blocked) is not None:
            H.add_edge(u, v)
    comp_of: dict = {}
    sizes: list[int] = []
    for i, comp in enumerate(nx.strongly_connected_components(H)):
        sizes.append(len(comp))
        for n in comp:
            comp_of[n] = i
    result = (comp_of, int(np.argmax(sizes)))
    _CACHE[key] = result
    if len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return result


def _nearest_in(G, lat: float, lon: float, comp_of: dict, comp: int) -> tuple[Optional[int], float]:
    ids, lats, lons = _node_index(G)
    k_lat = np.pi / 180 * EARTH_RADIUS_M
    k_lon = k_lat * np.cos(np.radians(lat))
    d2 = ((lats - lat) * k_lat) ** 2 + ((lons - lon) * k_lon) ** 2
    mask = np.fromiter((comp_of.get(int(n)) == comp for n in ids), dtype=bool, count=len(ids))
    if not mask.any():
        return None, float("inf")
    d2 = np.where(mask, d2, np.inf)
    i = int(d2.argmin())
    return int(ids[i]), float(np.sqrt(d2[i]))


def _resnap(G, pt: tuple[float, float], s: Snap, comp_of: dict, main: int) -> Snap:
    if s.distance_m < config.SNAP_RESNAP_MIN_M or comp_of.get(s.node) == main:
        return s
    node, d = _nearest_in(G, pt[0], pt[1], comp_of, main)
    if node is None or d > s.distance_m + config.SNAP_MAX_EXTRA_M:
        return s
    return Snap(node, d, True, s.node, s.distance_m)


def snap_points(
    G,
    start: tuple[float, float],
    end: Optional[tuple[float, float]],
    prefs: Prefs,
    blocked: Mapping[EdgeKey, object],
) -> tuple[Snap, Optional[Snap]]:
    """Snap start (and end, if given) for a route under ``prefs``.

    With ``end=None`` (routing to a building), only the start can move: entrances are doors and
    always keep their exact junction.
    """
    s = Snap(*nearest_node(G, *start))
    e = Snap(*nearest_node(G, *end)) if end is not None else None
    far = s.distance_m >= config.SNAP_RESNAP_MIN_M or (e is not None and e.distance_m >= config.SNAP_RESNAP_MIN_M)
    if not far:
        return s, e
    comp_of, main = components(G, prefs, blocked)
    if e is not None and comp_of.get(s.node) == comp_of.get(e.node):
        return s, e  # they can already reach each other
    s = _resnap(G, start, s, comp_of, main)
    if e is not None:
        e = _resnap(G, end, e, comp_of, main)
    return s, e
