"""A*/Dijkstra wrappers: standard (shortest, stairs OK) vs. accessible (step-free, grade-limited)."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Mapping, Optional

import networkx as nx

from ..schemas import RouteMeta, RouteRequest, RouteResponse, RouteResult, SnapInfo
from ..utils.geo import haversine_m, nearest_node, node_latlon
from .closures import ClosureIndex, resolve_closures
from .serialize import not_found, serialize_path
from .weights import ACCESSIBLE, STANDARD, EdgeKey, Prefs, make_weight_fn


def find_path(
    G,
    source: int,
    target: int,
    prefs: Prefs,
    blocked: Optional[Mapping[EdgeKey, object]] = None,
    algorithm: str = "astar",
) -> Optional[list[int]]:
    """Least-cost node path under ``prefs``, or None if the target is unreachable."""
    if source == target:
        return [source]

    weight = make_weight_fn(prefs, blocked or {})

    try:
        if algorithm == "dijkstra":
            return nx.dijkstra_path(G, source, target, weight=weight)

        # Edge cost >= edge length >= straight-line distance, so haversine is admissible.
        tlat, tlon = G.nodes[target]["y"], G.nodes[target]["x"]

        def heuristic(n, _t):
            nd = G.nodes[n]
            return haversine_m(nd["y"], nd["x"], tlat, tlon)

        return nx.astar_path(G, source, target, heuristic=heuristic, weight=weight)
    except nx.NetworkXNoPath:
        return None


def _route_one(G, src: int, dst: int, prefs: Prefs, idx: ClosureIndex, max_grade_note: str) -> RouteResult:
    path = find_path(G, src, dst, prefs, idx.blocked_for(prefs.mode))
    if path is None:
        return not_found(prefs, idx, f"No route found{max_grade_note}")
    return serialize_path(G, path, prefs, idx)


def plan_routes(G, req: RouteRequest, now: Optional[datetime] = None) -> RouteResponse:
    """Stateless entry point: everything needed is in ``req`` (including closures)."""
    t0 = time.perf_counter()

    src, src_d = nearest_node(G, req.start.lat, req.start.lon)
    dst, dst_d = nearest_node(G, req.end.lat, req.end.lon)
    idx = resolve_closures(G, req.closures, now)

    acc_prefs = Prefs(ACCESSIBLE, req.max_grade_pct, req.avoid_steps)
    note = f" that is step-free and under {req.max_grade_pct:g}% grade with current closures"
    accessible = _route_one(G, src, dst, acc_prefs, idx, note if req.avoid_steps else " under the grade limit")

    standard = None
    if req.include_standard:
        standard = _route_one(G, src, dst, Prefs(STANDARD, req.max_grade_pct, False), idx, "")

    def snap(n: int, d: float) -> SnapInfo:
        lat, lon = node_latlon(G, n)
        return SnapInfo(node_id=n, lat=lat, lon=lon, snap_distance_m=round(d, 1))

    meta = RouteMeta(
        compute_ms=round((time.perf_counter() - t0) * 1000, 1),
        graph_nodes=G.number_of_nodes(),
        graph_edges=G.number_of_edges(),
        max_grade_pct=req.max_grade_pct,
        closures_received=len(req.closures),
        closures_active=idx.active_count,
        closures_expired=idx.expired_count,
        start=snap(src, src_d),
        end=snap(dst, dst_d),
    )
    return RouteResponse(accessible=accessible, standard=standard, meta=meta)
