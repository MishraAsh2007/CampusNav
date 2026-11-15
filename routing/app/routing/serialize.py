"""Path -> GeoJSON + per-segment data (with template directions) for the response."""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from .. import config
from ..schemas import RouteResult, Segment
from ..utils.geo import angle_diff_deg, bearing_deg, compass_name, edge_coords, m_to_ft
from .closures import ClosureIndex
from .weights import ACCESSIBLE, EdgeKey, Prefs, best_parallel_edge

MERGE_TURN_DEG = 30.0


def _fmt_ft(m: float) -> str:
    ft = m_to_ft(m)
    if ft < 100:
        return f"{int(round(ft / 5.0) * 5) or 5} ft"
    if ft < 1000:
        return f"{int(round(ft / 10.0) * 10)} ft"
    return f"{ft / 5280:.1f} mi"


def _turn_phrase(diff: float) -> str:
    a = abs(diff)
    side = "right" if diff > 0 else "left"
    if a < MERGE_TURN_DEG:
        return "Continue"
    if a < 60:
        return f"Bear {side}"
    if a < 135:
        return f"Turn {side}"
    return f"Turn sharply {side}"


def _instruction(seg: dict, prev_bearing: Optional[float]) -> str:
    name = seg["name"]
    if prev_bearing is None:
        text = f"Head {compass_name(seg['bearing'])}"
        text += f" on {name}" if name else ""
    else:
        phrase = _turn_phrase(angle_diff_deg(prev_bearing, seg["bearing"]))
        if phrase == "Continue":
            text = phrase + (f" on {name}" if name else "")
        else:
            text = phrase + (f" onto {name}" if name else "")

    kind = seg["kind"]
    if kind == "steps":
        n = seg["step_count"]
        text += f", taking the stairs ({n} steps)" if n else ", taking the stairs"
    elif kind == "ramp":
        text += ", on a ramp"
    elif kind == "elevator":
        text += ", using the elevator"
    elif kind == "crossing":
        text += ", crossing the street"

    text += f" for {_fmt_ft(seg['length_m'])}"

    g = seg["max_grade_pct"]
    if kind not in ("steps", "elevator") and g >= 1.0:
        text += f", about {round(g)}% grade"
    return text


def _collect_edges(G, path: Sequence[int], prefs: Prefs, blocked: Mapping[EdgeKey, object]) -> list[dict]:
    edges = []
    for u, v in zip(path[:-1], path[1:]):
        best = best_parallel_edge(G[u][v], u, v, prefs, blocked)
        if best is None:  # cannot happen for a path we just found, but stay defensive
            continue
        _, data, _ = best
        coords = edge_coords(G, u, v, data)
        steps = data.get("step_count")
        edges.append(
            {
                "id": f"{u}_{v}",
                "kind": data.get("kind", "path"),
                "name": data.get("name") or None,
                "length": float(data.get("length") or 0.0),
                "grade": float(data.get("grade") or 0.0),
                "step_count": int(steps) if steps not in (None, "") else None,
                "coords": coords,
                "bearing": bearing_deg(*coords[0], *coords[-1]),
            }
        )
    return edges


def _merge(edges: list[dict]) -> list[dict]:
    """Merge consecutive edges with the same kind/name that continue roughly straight."""
    merged: list[dict] = []
    for e in edges:
        last = merged[-1] if merged else None
        if (
            last
            and last["kind"] == e["kind"]
            and last["name"] == e["name"]
            and abs(angle_diff_deg(last["end_bearing"], e["bearing"])) < MERGE_TURN_DEG
        ):
            last["edge_ids"].append(e["id"])
            last["coords"].extend(e["coords"][1:])
            last["grade_len"] += e["grade"] * e["length"]
            last["length"] += e["length"]
            last["max_abs_grade"] = max(last["max_abs_grade"], abs(e["grade"]))
            if e["step_count"]:
                last["step_count"] = (last["step_count"] or 0) + e["step_count"]
            last["end_bearing"] = e["bearing"]
        else:
            merged.append(
                {
                    "edge_ids": [e["id"]],
                    "kind": e["kind"],
                    "name": e["name"],
                    "coords": list(e["coords"]),
                    "length": e["length"],
                    "grade_len": e["grade"] * e["length"],
                    "max_abs_grade": abs(e["grade"]),
                    "step_count": e["step_count"],
                    "bearing": e["bearing"],
                    "end_bearing": e["bearing"],
                }
            )
    return merged


def serialize_path(
    G,
    path: Sequence[int],
    prefs: Prefs,
    closure_index: ClosureIndex,
) -> RouteResult:
    mode = prefs.mode
    blocked = closure_index.blocked_for(mode)
    merged = _merge(_collect_edges(G, path, prefs, blocked))

    segments: list[Segment] = []
    prev_bearing: Optional[float] = None
    route_coords: list[list[float]] = []
    total_len = steps_len = 0.0
    step_count = 0
    max_grade = 0.0

    for m in merged:
        length = m["length"]
        grade = m["grade_len"] / length if length else 0.0
        seg_view = {
            "name": m["name"],
            "kind": m["kind"],
            "bearing": m["bearing"],
            "length_m": length,
            "step_count": m["step_count"],
            "max_grade_pct": m["max_abs_grade"],
        }
        lonlat = [[lon, lat] for lat, lon in m["coords"]]
        segments.append(
            Segment(
                edge_ids=m["edge_ids"],
                kind=m["kind"],
                name=m["name"],
                length_m=round(length, 1),
                grade_pct=round(grade, 1),
                max_grade_pct=round(m["max_abs_grade"], 1),
                step_count=m["step_count"],
                bearing_deg=round(m["bearing"], 0),
                instruction=_instruction(seg_view, prev_bearing),
                geometry={"type": "LineString", "coordinates": lonlat},
            )
        )
        prev_bearing = m["end_bearing"]

        total_len += length
        if m["kind"] == "steps":
            steps_len += length
            step_count += m["step_count"] or 0
        else:
            max_grade = max(max_grade, m["max_abs_grade"])

        start = 1 if route_coords else 0
        route_coords.extend(lonlat[start:])

    speed = config.SPEED_ACCESSIBLE_MPS if mode == ACCESSIBLE else config.SPEED_STANDARD_MPS
    applied = [a for a in closure_index.applied_for(mode)]

    return RouteResult(
        mode=mode,
        found=True,
        distance_m=round(total_len, 1),
        duration_s=round(total_len / speed, 0),
        max_grade_pct=round(max_grade, 1),
        step_count=step_count,
        steps_length_m=round(steps_len, 1),
        is_step_free=steps_len == 0,
        geometry={
            "type": "Feature",
            "properties": {"mode": mode},
            "geometry": {"type": "LineString", "coordinates": route_coords},
        },
        segments=segments,
        closures_applied=applied,
        last_confirmed_at=closure_index.last_confirmed(mode),
    )


def not_found(prefs: Prefs, closure_index: ClosureIndex, reason: str) -> RouteResult:
    return RouteResult(
        mode=prefs.mode,
        found=False,
        reason=reason,
        closures_applied=list(closure_index.applied_for(prefs.mode)),
        last_confirmed_at=closure_index.last_confirmed(prefs.mode),
    )
