"""Edge cost function: stairs, grade, closures.

cost = length_m * multiplier, with multiplier >= 1 so a straight-line (haversine)
A* heuristic is always admissible. Returning ``None`` means "edge is impassable";
NetworkX treats that as a missing edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from .. import config

EdgeKey = tuple[int, int, int]  # (u, v, multigraph key)

STANDARD = "standard"
ACCESSIBLE = "accessible"


@dataclass(frozen=True)
class Prefs:
    mode: str = ACCESSIBLE
    max_grade_pct: float = config.DEFAULT_MAX_GRADE_PCT
    avoid_steps: bool = True


def _grade_abs(data: Mapping) -> float:
    g = data.get("grade_abs")
    if g is None:
        g = abs(data.get("grade") or 0.0)
    return float(g)


def edge_cost(data: Mapping, prefs: Prefs) -> Optional[float]:
    """Cost of traversing one directed edge, or None if impassable for these prefs."""
    length = float(data.get("length") or 0.0)

    if prefs.mode == STANDARD:
        # Plain shortest path: ignores stairs and slope.
        return length

    kind = data.get("kind", "path")

    if data.get("accessible") is False:
        return None  # ground truth says not step-free

    multiplier = 1.0

    if kind == "steps":
        if prefs.avoid_steps:
            return None
        multiplier *= config.STEP_PENALTY_MULTIPLIER
    elif kind == "crossing":
        multiplier *= config.CROSSING_PENALTY_MULTIPLIER

    if kind != "steps":
        grade = _grade_abs(data)
        limit = prefs.max_grade_pct
        if grade > limit:
            if length >= config.MIN_HARD_BLOCK_LENGTH_M:
                return None
            # Short edge: probably DEM noise, so penalize instead of cutting the graph.
            multiplier *= 1.0 + config.GRADE_SOFT_PENALTY * 2
        else:
            soft_start = limit * config.GRADE_SOFT_START_FRACTION
            if limit > 0 and grade > soft_start:
                frac = (grade - soft_start) / max(limit - soft_start, 1e-9)
                multiplier *= 1.0 + config.GRADE_SOFT_PENALTY * frac

    return length * multiplier


def best_parallel_edge(
    parallel: Mapping[int, Mapping],
    u: int,
    v: int,
    prefs: Prefs,
    blocked: Mapping[EdgeKey, object],
) -> Optional[tuple[int, Mapping, float]]:
    """Cheapest passable edge among parallel edges u->v. Returns (key, data, cost)."""
    best: Optional[tuple[int, Mapping, float]] = None
    for k, data in parallel.items():
        if (u, v, k) in blocked:
            continue
        c = edge_cost(data, prefs)
        if c is not None and (best is None or c < best[2]):
            best = (k, data, c)
    return best


def make_weight_fn(prefs: Prefs, blocked: Mapping[EdgeKey, object]) -> Callable:
    """Weight callable for networkx on a MultiDiGraph (receives {key: data})."""

    def weight(u, v, parallel):
        best = best_parallel_edge(parallel, u, v, prefs, blocked)
        return None if best is None else best[2]

    return weight
