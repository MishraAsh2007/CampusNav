"""Destination look-ahead: pick which entrance of the destination building to route to.

The outdoor route is shown first and the indoor route later (on user request), but the
entrance the outdoor route ends at has to suit the indoor leg. This module checks, at
planning time:

  * which entrances are step-free and not closed,
  * whether the building has a working elevator (by active elevator_out closures),
  * which usable entrance is cheapest: outdoor route cost + straight-line distance from
    the door to the nearest working elevator (only when the room needs an elevator).

Ranking among usable entrances: no key card first, then (if an elevator is needed)
entrances marked accessible to all floors, then lowest cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

from .. import config
from ..schemas import (
    Closure,
    ClosureType,
    Destination,
    DestinationEntrance,
    DestinationPlan,
    ElevatorStatus,
    EntranceOption,
)
from ..utils.geo import haversine_m, m_to_ft, nearest_node
from .closures import _aware, is_active
from .pathfinding import find_path, path_cost
from .weights import EdgeKey, Prefs


@dataclass
class PlannedTarget:
    plan: DestinationPlan
    node: Optional[int] = None          # graph node both routes should end at
    snap_m: float = 0.0
    accessible_path: Optional[list[int]] = None  # already computed for the chosen entrance
    fallback_node: Optional[int] = None  # for the standard route when no entrance is usable
    fallback_snap_m: float = 0.0


def _near(c: Closure, lat: float, lon: float, slack: float = 0.0) -> bool:
    return c.lat is not None and c.lon is not None and haversine_m(c.lat, c.lon, lat, lon) <= c.radius_m + slack


def _elevator_status(dest: Destination, active: list[Closure]) -> tuple[ElevatorStatus, list[tuple[float, float]]]:
    """Returns the status and the coordinates of elevators believed to be working."""
    b = dest.building
    total = b.total_elevators
    located = [(e.lat, e.lng) for e in b.elevators if e.lat is not None and e.lng is not None]
    elevator_closures = [c for c in active if c.type == ClosureType.elevator_out and c.lat is not None]

    matched: list[Closure] = []
    out_located: set[int] = set()
    building_wide = False
    for c in elevator_closures:
        hits = [i for i, (la, lo) in enumerate(located) if _near(c, la, lo, config.DEST_ELEVATOR_MATCH_SLACK_M)]
        if hits:
            out_located.update(hits)
            matched.append(c)
        elif haversine_m(c.lat, c.lon, b.lat, b.lng) <= max(config.DEST_BUILDING_MATCH_M, c.radius_m):
            # Can't tell which car: be conservative, as for "may be unavailable" notices.
            building_wide = True
            matched.append(c)

    # Elevators the building data itself marks out of service (e.g. the map UI's status field).
    flagged = [e for e in b.elevators if (e.status or "").lower() in ("out_of_service", "out", "down")]
    flagged_located = {i for i, e in enumerate(e for e in b.elevators if e.lat is not None and e.lng is not None)
                       if (e.status or "").lower() in ("out_of_service", "out", "down")}
    out_located |= flagged_located
    unlocated_flagged = len(flagged) - len(flagged_located)

    possibly_out = total if building_wide else min(total, len(out_located) + unlocated_flagged)
    working = [] if building_wide else [p for i, p in enumerate(located) if i not in out_located]
    stamps = [_aware(c.confirmed_at or c.reported_at) for c in matched if (c.confirmed_at or c.reported_at)]
    status = ElevatorStatus(
        total=total,
        possibly_out=possibly_out,
        working=total - possibly_out,
        located=len(located),
        closure_ids=[c.id for c in matched],
        last_confirmed_at=max(stamps) if stamps else None,
    )
    return status, working


def _door_issue(e: DestinationEntrance, dest: Destination):
    return next((d for d in dest.door_issues
                 if haversine_m(d.lat, d.lng, e.lat, e.lng) <= max(15.0, d.radius_m)), None)


def _entrance_blockers(e: DestinationEntrance, active: list[Closure]) -> list[Closure]:
    return [c for c in active if c.type != ClosureType.elevator_out and _near(c, e.lat, e.lng)]


def plan_destination(
    G,
    dest: Destination,
    closures: list[Closure],
    now: datetime,
    source: int,
    prefs: Prefs,
    blocked: Mapping[EdgeKey, object],
) -> PlannedTarget:
    b = dest.building
    active = [c for c in closures if is_active(c, now)]
    elevators, working_elevators = _elevator_status(dest, active)
    reachable = elevators.working > 0
    warnings: list[str] = []

    # ---- elevator warnings (before choosing a door, so the user knows up front)
    if dest.needs_elevator and elevators.total == 0:
        warnings.append(f"{b.name} has no elevator on record, so upper floors may not be reachable step-free.")
    elif dest.needs_elevator and not reachable:
        warnings.append(
            f"All {elevators.total} elevator(s) at {b.name} may be out of service, so floors above "
            "the entrance level are not reachable step-free right now."
        )
    elif elevators.possibly_out:
        warnings.append(
            f"{elevators.possibly_out} of {elevators.total} elevator(s) at {b.name} may be out of service."
        )

    # ---- evaluate each entrance
    options: list[tuple[tuple, EntranceOption, int, float, list[int]]] = []
    all_options: list[EntranceOption] = []
    nearest_any: Optional[tuple[float, int, float]] = None
    for e in b.entrances:
        node, snap = nearest_node(G, e.lat, e.lng)
        straight = haversine_m(G.nodes[source]["y"], G.nodes[source]["x"], e.lat, e.lng)
        if nearest_any is None or straight < nearest_any[0]:
            nearest_any = (straight, node, snap)

        issue = _door_issue(e, dest)
        opt = EntranceOption(
            id=e.id, name=e.name, lat=e.lat, lon=e.lng, step_free=e.step_free, usable=False,
            auto_door=e.auto_door, key_card_required=e.IsKeyCardRequired,
            accessible_to_all_floors=e.isAccessibleToAllFloors,
            door_issue=(issue.description or "door opener reported broken") if issue else None,
        )
        all_options.append(opt)
        if not e.step_free:
            opt.reasons.append("not step-free")
        for c in _entrance_blockers(e, active):
            opt.reasons.append(f"closed: {c.description or c.type.value} ({c.id})")
        if opt.reasons:
            continue

        path = find_path(G, source, node, prefs, blocked)
        if path is None:
            opt.reasons.append(f"no step-free route under {prefs.max_grade_pct:g}% grade with current closures")
            continue
        cost, length = path_cost(G, path, prefs, blocked)
        opt.usable = True
        opt.route_distance_m = round(length, 1)

        indoor = 0.0
        if dest.needs_elevator and working_elevators:
            indoor = min(haversine_m(e.lat, e.lng, la, lo) for la, lo in working_elevators)
            opt.to_working_elevator_m = round(indoor, 1)
        if e.IsKeyCardRequired:
            opt.reasons.append("key card required")
        if dest.needs_elevator and e.isAccessibleToAllFloors is False:
            opt.reasons.append("marked as not giving access to all floors")

        # Door opener: with need_automatic_door, a door with a working opener always ranks first.
        powered = e.auto_door is not False and not (issue and issue.closed)
        door_penalty = 0.0
        if issue:
            door_penalty += config.DEST_DOOR_ISSUE_PENALTY_M if issue.closed else config.DEST_DOOR_DEGRADED_PENALTY_M
            opt.reasons.append(f"door opener: {opt.door_issue}")
        if dest.need_automatic_door and not powered:
            opt.reasons.append("no working automatic door opener")
        if dest.need_automatic_door and e.door_type == "push-button":
            door_penalty += config.DEST_PUSH_BUTTON_PENALTY_M

        rank = (
            bool(e.IsKeyCardRequired),
            dest.need_automatic_door and not powered,
            dest.needs_elevator and e.isAccessibleToAllFloors is False,
            cost + config.DEST_INDOOR_WEIGHT * indoor + door_penalty,
        )
        options.append((rank, opt, node, snap, path))

    fallback, fallback_snap = (nearest_any[1], nearest_any[2]) if nearest_any else nearest_node(G, b.lat, b.lng)

    if not b.entrances:
        warnings.append(f"No entrance data for {b.name}; routing to the building's center point instead.")
        node, snap = nearest_node(G, b.lat, b.lng)
        plan = DestinationPlan(
            building_id=b.id, building_name=b.name, room=dest.room, needs_elevator=dest.needs_elevator,
            upper_floors_reachable=reachable, entrances=[], elevators=elevators, warnings=warnings,
        )
        return PlannedTarget(plan, node, snap, find_path(G, source, node, prefs, blocked), fallback, fallback_snap)

    if not options:
        candidates = [o for o in all_options if o.step_free and not any(r.startswith("closed") for r in o.reasons)]
        if candidates and all(any(r.startswith("no step-free route") for r in o.reasons) for o in candidates):
            # Every open step-free door is unreachable: the start, not the building, is usually the problem.
            warnings.append(
                f"No step-free route under {prefs.max_grade_pct:g}% grade from your starting point to any "
                f"entrance of {b.name}. The start may be cut off by stairs or a steep path; try a "
                "different starting point or a higher grade limit."
            )
        else:
            warnings.append(f"No usable step-free entrance to {b.name} right now. See `entrances` for reasons.")
        plan = DestinationPlan(
            building_id=b.id, building_name=b.name, room=dest.room, needs_elevator=dest.needs_elevator,
            upper_floors_reachable=reachable, entrances=all_options, elevators=elevators, warnings=warnings,
        )
        return PlannedTarget(plan, fallback_node=fallback, fallback_snap_m=fallback_snap)

    options.sort(key=lambda o: o[0])
    _, chosen, node, snap, path = options[0]
    chosen.chosen = True

    if chosen.key_card_required:
        warnings.append(f"{chosen.name} needs a key card; no other step-free entrance is usable.")
    if chosen.door_issue:
        warnings.append(f"{chosen.name}: {chosen.door_issue}.")
    elif chosen.auto_door is False:
        warnings.append(f"{chosen.name} has no automatic door opener.")
    if snap > config.DEST_ENTRANCE_SNAP_WARN_M:
        warnings.append(
            f"{chosen.name} is about {round(m_to_ft(snap), -1):.0f} ft from the nearest mapped path; "
            "the last stretch may not be shown."
        )
    if chosen.to_working_elevator_m is not None and len(options) > 1:
        warnings.append(
            f"Using {chosen.name}: about {round(m_to_ft(chosen.to_working_elevator_m), -1):.0f} ft "
            "from a working elevator."
        )

    plan = DestinationPlan(
        building_id=b.id, building_name=b.name, room=dest.room, needs_elevator=dest.needs_elevator,
        upper_floors_reachable=reachable, entrance=chosen, entrances=all_options,
        elevators=elevators, warnings=warnings,
    )
    return PlannedTarget(plan, node, snap, path, fallback, fallback_snap)
