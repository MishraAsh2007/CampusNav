"""A*/Dijkstra wrappers: standard (shortest, stairs OK) vs. accessible (step-free, grade-limited)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Mapping, Optional

import networkx as nx

from ..schemas import RouteMeta, RouteRequest, RouteResponse, RouteResult, SnapInfo
from ..utils.geo import haversine_m, nearest_node, node_latlon
from .closures import ClosureIndex, resolve_closures
from .serialize import not_found, serialize_path
from .weights import ACCESSIBLE, STANDARD, EdgeKey, Prefs, best_parallel_edge, make_weight_fn


def path_cost(G, path: list[int], prefs: Prefs, blocked: Mapping[EdgeKey, object]) -> tuple[float, float]:
    """(weighted cost, length in meters) of a node path, using the edges the router would pick."""
    cost = length = 0.0
    for u, v in zip(path[:-1], path[1:]):
        best = best_parallel_edge(G[u][v], u, v, prefs, blocked)
        if best is None:
            return float("inf"), float("inf")
        cost += best[2]
        length += float(best[1].get("length") or 0.0)
    return cost, length


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


def _route_one(
    G, src: int, dst: int, prefs: Prefs, idx: ClosureIndex, max_grade_note: str,
    path: Optional[list[int]] = None,
) -> RouteResult:
    if path is None:
        path = find_path(G, src, dst, prefs, idx.blocked_for(prefs.mode))
    if path is None:
        return not_found(prefs, idx, f"No route found{max_grade_note}")
    return serialize_path(G, path, prefs, idx)


def plan_routes(G, req: RouteRequest, now: Optional[datetime] = None) -> RouteResponse:
    """Stateless entry point: everything needed is in ``req`` (including closures)."""
    from .destination import plan_destination  # local import: destination uses find_path

    t0 = time.perf_counter()
    now = now or datetime.now(timezone.utc)

    src, src_d = nearest_node(G, req.start.lat, req.start.lon)
    idx = resolve_closures(G, req.closures, now)
    acc_prefs = Prefs(ACCESSIBLE, req.max_grade_pct, req.avoid_steps)
    std_prefs = Prefs(STANDARD, req.max_grade_pct, False)
    note = f" that is step-free and under {req.max_grade_pct:g}% grade with current closures"
    if not req.avoid_steps:
        note = " under the grade limit"

    plan = None
    acc_path = None
    if req.destination is not None:
        # Look ahead: pick the entrance that suits the indoor leg; both routes end there.
        target = plan_destination(
            G, req.destination, req.closures, now, src, acc_prefs, idx.blocked_for(ACCESSIBLE)
        )
        plan = target.plan
        acc_path = target.accessible_path
        dst, dst_d = (target.node, target.snap_m) if target.node is not None else (target.fallback_node, target.fallback_snap_m)
        if target.node is None:
            accessible = not_found(acc_prefs, idx, f"No usable step-free entrance to {plan.building_name}")
        else:
            accessible = _route_one(G, src, dst, acc_prefs, idx, note, path=acc_path)
    else:
        dst, dst_d = nearest_node(G, req.end.lat, req.end.lon)
        accessible = _route_one(G, src, dst, acc_prefs, idx, note)

    standard = None
    if req.include_standard:
        standard = _route_one(G, src, dst, std_prefs, idx, "")

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
        closures_pending=idx.pending_count,
        start=snap(src, src_d),
        end=snap(dst, dst_d),
    )
    return RouteResponse(accessible=accessible, standard=standard, destination=plan, meta=meta)
