"""Map closures (lat/lon + radius, or explicit edge IDs) onto affected graph edges.

Which routes a closure affects:
  * construction, path_closed -> everyone (standard + accessible)
  * elevator_out              -> accessible only, elevator edges within the radius
  * ramp_blocked              -> accessible only, ramp edges within the radius
                                 (falls back to every edge in radius if no ramp is mapped there)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..schemas import AppliedClosure, Closure, ClosureType
from ..utils.geo import edge_coords, haversine_m, point_to_polyline_m
from .weights import ACCESSIBLE, STANDARD, EdgeKey

AFFECTS_STANDARD = {ClosureType.construction, ClosureType.path_closed}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_pending(closure: Closure, now: Optional[datetime] = None) -> bool:
    """Scheduled for later (e.g. an official notice posted ahead of time)."""
    now = now or datetime.now(timezone.utc)
    start = _aware(closure.starts_at)
    return start is not None and start > now


def is_active(closure: Closure, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    exp = _aware(closure.expires_at)
    return (exp is None or exp > now) and not is_pending(closure, now)


@dataclass
class ClosureIndex:
    """Result of resolving a closure list against a graph."""

    blocked: dict[str, dict[EdgeKey, set[str]]] = field(
        default_factory=lambda: {STANDARD: {}, ACCESSIBLE: {}}
    )
    applied: dict[str, list[AppliedClosure]] = field(
        default_factory=lambda: {STANDARD: [], ACCESSIBLE: []}
    )
    active_count: int = 0
    expired_count: int = 0
    pending_count: int = 0

    def blocked_for(self, mode: str) -> dict[EdgeKey, set[str]]:
        return self.blocked[mode]

    def applied_for(self, mode: str) -> list[AppliedClosure]:
        return self.applied[mode]

    def last_confirmed(self, mode: str) -> Optional[datetime]:
        stamps = [_aware(a.confirmed_at) for a in self.applied[mode] if a.edges_blocked and a.confirmed_at]
        return max(stamps) if stamps else None


def _edge_geoms(G) -> list:
    """Cache (u, v, k, data, coords, mid_lat, mid_lon, half_len) for every edge on the graph."""
    cached = G.graph.get("_edge_geoms")
    if cached is None:
        cached = []
        for u, v, k, data in G.edges(keys=True, data=True):
            coords = edge_coords(G, u, v, data)
            mid = coords[len(coords) // 2]
            cached.append((u, v, k, data, coords, mid[0], mid[1], float(data.get("length") or 0) / 2))
        G.graph["_edge_geoms"] = cached
    return cached


def _edges_near(G, lat: float, lon: float, radius_m: float):
    for u, v, k, data, coords, mlat, mlon, half in _edge_geoms(G):
        # Cheap reject using the midpoint, then exact point-to-polyline distance.
        if haversine_m(lat, lon, mlat, mlon) > radius_m + half + 1.0:
            continue
        if point_to_polyline_m(lat, lon, coords) <= radius_m:
            yield (u, v, k), data


def _matching_edges(G, c: Closure) -> list[EdgeKey]:
    keys: list[EdgeKey] = []

    if c.edge_ids:
        for eid in c.edge_ids:
            try:
                a, b = (int(x) for x in eid.split("_"))
            except ValueError:
                continue
            for x, y in ((a, b), (b, a)):
                if G.has_edge(x, y):
                    keys.extend((x, y, k) for k in G[x][y])

    if c.lat is not None and c.lon is not None:
        near = list(_edges_near(G, c.lat, c.lon, c.radius_m))
        if c.type == ClosureType.elevator_out:
            keys.extend(key for key, d in near if d.get("kind") == "elevator")
        elif c.type == ClosureType.ramp_blocked:
            ramps = [key for key, d in near if d.get("kind") == "ramp"]
            keys.extend(ramps or [key for key, _ in near])
        else:
            keys.extend(key for key, _ in near)

    return list(dict.fromkeys(keys))  # de-dupe, keep order


def resolve_closures(G, closures: Iterable[Closure], now: Optional[datetime] = None) -> ClosureIndex:
    """Turn a stateless list of closures into per-mode blocked-edge sets."""
    idx = ClosureIndex()
    now = now or datetime.now(timezone.utc)
    for c in closures:
        if is_pending(c, now):
            idx.pending_count += 1
            continue
        if not is_active(c, now):
            idx.expired_count += 1
            continue
        idx.active_count += 1

        keys = _matching_edges(G, c)
        modes = [ACCESSIBLE] + ([STANDARD] if c.type in AFFECTS_STANDARD else [])
        for mode in modes:
            for key in keys:
                idx.blocked[mode].setdefault(key, set()).add(c.id)
            idx.applied[mode].append(
                AppliedClosure(
                    id=c.id,
                    type=c.type,
                    edges_blocked=len(keys),
                    confirmed_at=c.confirmed_at or c.reported_at,
                    expires_at=c.expires_at,
                    description=c.description,
                )
            )
    return idx
