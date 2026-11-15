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
from ..indoor.elevators import evaluate as evaluate_elevators
from ..utils.geo import haversine_m, m_to_ft, nearest_node
from .closures import AFFECTS_STANDARD, _aware, is_active
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
    # The standard (shortest) route picks its own entrance: nearest open door, steps allowed.
    standard_node: Optional[int] = None
    standard_snap_m: float = 0.0
    standard_path: Optional[list[int]] = None


def _near(c: Closure, lat: float, lon: float, slack: float = 0.0) -> bool:
    return c.lat is not None and c.lon is not None and haversine_m(c.lat, c.lon, lat, lon) <= c.radius_m + slack


def _elevator_status(dest: Destination, active: list[Closure]) -> tuple[ElevatorStatus, list[tuple[float, float]]]:
    """Returns the status and the coordinates of elevators believed to be working."""
    return evaluate_elevators(dest.building, active)


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
    std_prefs: Optional[Prefs] = None,
    std_blocked: Optional[Mapping[EdgeKey, object]] = None,
    std_source: Optional[int] = None,
) -> PlannedTarget:
    b = dest.building
    step_free = prefs.avoid_steps  # only exclude doors with steps if the user asked for step-free
    route_word = "step-free route" if step_free else "route"
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
        msg = f"{elevators.possibly_out} of {elevators.total} elevators at {b.name} may be out of service"
        if elevators.unattributed_out:
            msg += " (not known which)"
        msg += f"; the other{'s' if elevators.working != 1 else ''} should still reach upper floors."
        warnings.append(msg)

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
        if not e.step_free and step_free:
            opt.reasons.append("not step-free")
        for c in _entrance_blockers(e, active):
            opt.reasons.append(f"closed: {c.description or c.type.value} ({c.id})")
        if opt.reasons:
            continue

        path = find_path(G, source, node, prefs, blocked)
        if path is None:
            opt.reasons.append(f"no {route_word} under {prefs.max_grade_pct:g}% grade with current closures")
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
        candidates = [o for o in all_options
                      if (o.step_free or not step_free) and not any(r.startswith("closed") for r in o.reasons)]
        if candidates and all(any(r.startswith(f"no {route_word}") for r in o.reasons) for o in candidates):
            # Every open door is unreachable: the start, not the building, is usually the problem.
            warnings.append(
                f"No {route_word} under {prefs.max_grade_pct:g}% grade from your starting point to any "
                f"entrance of {b.name}. The start may be cut off by stairs or a steep path; try a "
                "different starting point or a higher grade limit."
            )
        else:
            kind = "step-free entrance" if step_free else "entrance"
            warnings.append(f"No usable {kind} to {b.name} right now. See `entrances` for reasons.")
        plan = DestinationPlan(
            building_id=b.id, building_name=b.name, room=dest.room, needs_elevator=dest.needs_elevator,
            upper_floors_reachable=reachable, entrances=all_options, elevators=elevators, warnings=warnings,
        )
        return _with_standard(PlannedTarget(plan, fallback_node=fallback, fallback_snap_m=fallback_snap),
                              G, dest, active, std_source if std_source is not None else source, std_prefs, std_blocked)

    options.sort(key=lambda o: o[0])
    _, chosen, node, snap, path = options[0]
    chosen.chosen = True

    if chosen.key_card_required:
        warnings.append(f"{chosen.name} needs a key card; no other {'step-free ' if step_free else ''}entrance is usable.")
    if chosen.door_issue:
        warnings.append(f"{chosen.name}: {chosen.door_issue}.")
    elif chosen.auto_door is False and (step_free or dest.need_automatic_door):
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
    return _with_standard(PlannedTarget(plan, node, snap, path, fallback, fallback_snap),
                          G, dest, active, std_source if std_source is not None else source, std_prefs, std_blocked)


def _with_standard(target: PlannedTarget, G, dest: Destination, active: list[Closure], source: int,
                   std_prefs: Optional[Prefs], std_blocked: Optional[Mapping[EdgeKey, object]]) -> PlannedTarget:
    """Shortest route: nearest entrance that isn't closed to everyone (stairs and doors don't matter)."""
    if std_prefs is None or not dest.building.entrances:
        return target
    best = best_open_door(G, dest.building.entrances, active, source, std_prefs, std_blocked or {})
    if best is None:
        return target
    length, e, node, snap, path = best
    target.standard_node, target.standard_snap_m, target.standard_path = node, snap, path
    target.plan.standard_entrance = door_option(e, length)
    return target


def open_doors(G, doors: list[DestinationEntrance], active: list[Closure]) -> list[tuple[DestinationEntrance, int, float]]:
    """Doors not closed to everyone (steps and openers don't matter), with their graph nodes."""
    out = []
    for e in doors:
        if any(c.type in AFFECTS_STANDARD and _near(c, e.lat, e.lng) for c in active):
            continue
        node, snap = nearest_node(G, e.lat, e.lng)
        out.append((e, node, snap))
    return out


def best_open_door(G, doors: list[DestinationEntrance], active: list[Closure], source: int,
                   prefs: Prefs, blocked: Mapping[EdgeKey, object]):
    """Shortest route from ``source`` to any open door: (length, door, node, snap, path) or None."""
    best = None
    for e, node, snap in open_doors(G, doors, active):
        path = find_path(G, source, node, prefs, blocked)
        if path is None:
            continue
        length = path_cost(G, path, prefs, blocked)[1]
        if best is None or length < best[0]:
            best = (length, e, node, snap, path)
    return best


def door_option(e: DestinationEntrance, length: Optional[float]) -> EntranceOption:
    return EntranceOption(
        id=e.id, name=e.name, lat=e.lat, lon=e.lng, step_free=e.step_free, usable=True, chosen=True,
        route_distance_m=round(length, 1) if length is not None else None, auto_door=e.auto_door,
        key_card_required=e.IsKeyCardRequired, accessible_to_all_floors=e.isAccessibleToAllFloors,
    )
