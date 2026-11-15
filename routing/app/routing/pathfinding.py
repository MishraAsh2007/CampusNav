"""A*/Dijkstra wrappers: standard (shortest, stairs OK) vs. accessible (step-free, grade-limited)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Mapping, Optional

import networkx as nx

from ..schemas import RouteMeta, RouteRequest, RouteResponse, RouteResult, SnapInfo
from ..utils.geo import haversine_m, nearest_node, node_latlon
from .closures import ClosureIndex, is_active, resolve_closures
from .serialize import not_found, serialize_path
from .snapping import Snap, snap_points
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

    idx = resolve_closures(G, req.closures, now)
    acc_prefs = Prefs(ACCESSIBLE, req.max_grade_pct, req.avoid_steps)
    std_prefs = Prefs(STANDARD, req.max_grade_pct, False)
    note = f" that is step-free and under {req.max_grade_pct:g}% grade with current closures"
    if not req.avoid_steps:
        note = " under the grade limit"

    blocked_a, blocked_s = idx.blocked_for(ACCESSIBLE), idx.blocked_for(STANDARD)

    # Standard route: plain nearest junction. Accessible route: avoid dead-end junctions.
    o = req.origin
    anchor = (req.start.lat, req.start.lon) if req.start is not None else (o.building.lat, o.building.lng)
    src, src_d = nearest_node(G, *anchor)
    end_pt = (req.end.lat, req.end.lon) if req.end is not None else None
    acc_s, acc_e = snap_points(G, anchor, end_pt, acc_prefs, blocked_a)
    acc_src = acc_s.node

    origin_plan = None
    origin_blocked = False
    if o is not None:
        # Look ahead from the start building: the best exit is the one with the cheapest whole trip.
        from .destination import best_open_door
        from .origin import plan_origin, standard_exit

        active = [c for c in req.closures if is_active(c, now)]
        dest_b = req.destination.building if req.destination is not None else None
        std_end = None
        if dest_b is None:
            std_end = nearest_node(G, req.end.lat, req.end.lon)[0]
        elif not dest_b.entrances:
            std_end = nearest_node(G, dest_b.lat, dest_b.lng)[0]

        def acc_onward(n):
            if req.destination is not None:
                t = plan_destination(G, req.destination, req.closures, now, n, acc_prefs, blocked_a)
                p = t.accessible_path if t.node is not None else None
            else:
                p = find_path(G, n, acc_e.node, acc_prefs, blocked_a)
            if p is None:
                return None
            c, length = path_cost(G, p, acc_prefs, blocked_a)
            return c, length, None

        def std_onward(n):
            if std_end is None:
                best = best_open_door(G, dest_b.entrances, active, n, std_prefs, blocked_s)
                return (best[0], best[0], None) if best else None
            p = find_path(G, n, std_end, std_prefs, blocked_s)
            if p is None:
                return None
            length = path_cost(G, p, std_prefs, blocked_s)[1]
            return length, length, None

        choice = plan_origin(G, o, active, acc_prefs, acc_onward)
        if req.include_standard:
            standard_exit(G, o, active, std_onward, choice)
        origin_plan = choice.plan
        if choice.node is not None:
            acc_src, acc_s = choice.node, Snap(choice.node, choice.snap_m)
        else:
            origin_blocked = True
            acc_src, acc_s = choice.fallback_node, Snap(choice.fallback_node, choice.fallback_snap_m)
        if choice.standard_node is not None:
            src, src_d = choice.standard_node, choice.standard_snap_m
        elif o.building.entrances:
            src, src_d = choice.fallback_node, choice.fallback_snap_m

    plan = None
    acc_path = None
    if req.destination is not None:
        # Look ahead: pick the entrance that suits the indoor leg.
        target = plan_destination(
            G, req.destination, req.closures, now, acc_src, acc_prefs, idx.blocked_for(ACCESSIBLE),
            std_prefs=std_prefs, std_blocked=idx.blocked_for(STANDARD), std_source=src,
        )
        plan = target.plan
        acc_path = target.accessible_path
        dst, dst_d = (target.node, target.snap_m) if target.node is not None else (target.fallback_node, target.fallback_snap_m)
        if target.node is None:
            accessible = not_found(acc_prefs, idx, f"No usable step-free entrance to {plan.building_name}")
        else:
            accessible = _route_one(G, acc_src, dst, acc_prefs, idx, note, path=acc_path)
        acc_e = Snap(dst, dst_d)
    else:
        dst, dst_d = nearest_node(G, req.end.lat, req.end.lon)
        accessible = _route_one(G, acc_src, acc_e.node, acc_prefs, idx, note)

    if origin_blocked:
        kind = "step-free exit" if req.avoid_steps else "exit"
        accessible = not_found(acc_prefs, idx, f"No usable {kind} from {origin_plan.building_name} leads to your destination")

    standard = None
    if req.include_standard:
        if req.destination is not None and target.standard_node is not None:
            standard = _route_one(G, src, target.standard_node, std_prefs, idx, "", path=target.standard_path)
        else:
            standard = _route_one(G, src, dst, std_prefs, idx, "")

    def snap(s: Snap) -> SnapInfo:
        lat, lon = node_latlon(G, s.node)
        return SnapInfo(
            node_id=s.node, lat=lat, lon=lon, snap_distance_m=round(s.distance_m, 1), moved=s.moved,
            original_snap_distance_m=round(s.original_distance_m, 1) if s.moved else None,
        )

    meta = RouteMeta(
        compute_ms=round((time.perf_counter() - t0) * 1000, 1),
        graph_nodes=G.number_of_nodes(),
        graph_edges=G.number_of_edges(),
        max_grade_pct=req.max_grade_pct,
        closures_received=len(req.closures),
        closures_active=idx.active_count,
        closures_expired=idx.expired_count,
        closures_pending=idx.pending_count,
        start=snap(acc_s),
        end=snap(acc_e),
    )
    return RouteResponse(accessible=accessible, standard=standard, origin=origin_plan, destination=plan, meta=meta)
