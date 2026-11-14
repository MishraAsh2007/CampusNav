"""Origin look-ahead: pick which exit of the starting building to leave by.

The user starts inside a building (indoor GPS is unreliable, so we know the building, not the
spot). Each exit is judged the same way as a destination entrance:

  * excluded if it has steps and the user needs step-free access, or is inside an active
    ramp / path / construction closure,
  * door-opener problems and ``need_automatic_door`` rank it the same way,
  * if the user is on a floor that needs an elevator (``needs_elevator``), the straight-line
    distance from the exit to the nearest working elevator is added, and a warning is given
    when no elevator works.

Unlike the destination, the cost of an exit is the cost of the WHOLE onward trip from it,
including the destination's own entrance choice, so the best exit/entrance pair wins.
Key cards are ignored: they lock doors from the outside, not the inside.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .. import config
from ..schemas import Closure, Destination, EntranceOption, OriginPlan
from ..utils.geo import haversine_m, m_to_ft, nearest_node
from .destination import _door_issue, _elevator_status, _entrance_blockers, door_option, open_doors
from .weights import Prefs

# onward(node) -> (cost, length_m, payload) for the rest of the trip from that exit, or None.
Onward = Callable[[int], Optional[tuple[float, float, Any]]]


@dataclass
class OriginChoice:
    plan: OriginPlan
    node: Optional[int] = None       # graph node the accessible route starts at
    snap_m: float = 0.0
    payload: Any = None              # whatever onward() returned for the chosen exit
    fallback_node: Optional[int] = None
    fallback_snap_m: float = 0.0
    standard_node: Optional[int] = None
    standard_snap_m: float = 0.0
    standard_payload: Any = None
    notes: list[str] = field(default_factory=list)


def plan_origin(G, origin: Destination, active: list[Closure], prefs: Prefs, onward: Onward) -> OriginChoice:
    b = origin.building
    step_free = prefs.avoid_steps
    elevators, working = _elevator_status(origin, active)
    can_reach_exit = elevators.working > 0 or not origin.needs_elevator
    warnings: list[str] = []

    if origin.needs_elevator and elevators.total == 0:
        warnings.append(f"{b.name} has no elevator on record, so you may not be able to reach an exit "
                        "step-free from an upper floor.")
    elif origin.needs_elevator and elevators.working == 0:
        warnings.append(f"All {elevators.total} elevator(s) at {b.name} may be out of service, so you may "
                        "not be able to get down to an exit step-free right now.")
    elif elevators.possibly_out and origin.needs_elevator:
        warnings.append(f"{elevators.possibly_out} of {elevators.total} elevator(s) at {b.name} may be out of service.")

    fb_node, fb_snap = nearest_node(G, b.lat, b.lng)
    if not b.entrances:
        warnings.append(f"No exit data for {b.name}; starting from the building's center point instead.")
        plan = OriginPlan(building_id=b.id, building_name=b.name, room=origin.room,
                          needs_elevator=origin.needs_elevator, can_reach_exit=can_reach_exit,
                          elevators=elevators, warnings=warnings)
        res = onward(fb_node)
        return OriginChoice(plan, fb_node, fb_snap, res[2] if res else None, fb_node, fb_snap)

    options = []
    all_options: list[EntranceOption] = []
    for e in b.entrances:
        node, snap = nearest_node(G, e.lat, e.lng)
        issue = _door_issue(e, origin)
        opt = EntranceOption(
            id=e.id, name=e.name, lat=e.lat, lon=e.lng, step_free=e.step_free, usable=False,
            auto_door=e.auto_door, accessible_to_all_floors=e.isAccessibleToAllFloors,
            door_issue=(issue.description or "door opener reported broken") if issue else None,
        )
        all_options.append(opt)
        if not e.step_free and step_free:
            opt.reasons.append("not step-free")
        for c in _entrance_blockers(e, active):
            opt.reasons.append(f"closed: {c.description or c.type.value} ({c.id})")
        if opt.reasons:
            continue
        res = onward(node)
        if res is None:
            opt.reasons.append("no route to the destination from this exit")
            continue
        cost, length, payload = res
        opt.usable = True
        opt.route_distance_m = round(length, 1)

        indoor = 0.0
        if origin.needs_elevator and working:
            indoor = min(haversine_m(e.lat, e.lng, la, lo) for la, lo in working)
            opt.to_working_elevator_m = round(indoor, 1)
        powered = e.auto_door is not False and not (issue and issue.closed)
        penalty = 0.0
        if issue:
            penalty += config.DEST_DOOR_ISSUE_PENALTY_M if issue.closed else config.DEST_DOOR_DEGRADED_PENALTY_M
            opt.reasons.append(f"door opener: {opt.door_issue}")
        if origin.need_automatic_door and not powered:
            opt.reasons.append("no working automatic door opener")
        if origin.need_automatic_door and e.door_type == "push-button":
            penalty += config.DEST_PUSH_BUTTON_PENALTY_M
        rank = (origin.need_automatic_door and not powered, cost + config.DEST_INDOOR_WEIGHT * indoor + penalty)
        options.append((rank, opt, node, snap, payload))

    if not options:
        kind = "step-free exit" if step_free else "exit"
        warnings.append(f"No usable {kind} from {b.name} leads to your destination right now. "
                        "See `exits` for reasons.")
        plan = OriginPlan(building_id=b.id, building_name=b.name, room=origin.room,
                          needs_elevator=origin.needs_elevator, can_reach_exit=can_reach_exit,
                          exits=all_options, elevators=elevators, warnings=warnings)
        return OriginChoice(plan, fallback_node=fb_node, fallback_snap_m=fb_snap)

    options.sort(key=lambda o: o[0])
    _, chosen, node, snap, payload = options[0]
    chosen.chosen = True
    if chosen.door_issue:
        warnings.append(f"{chosen.name}: {chosen.door_issue}.")
    elif chosen.auto_door is False and (step_free or origin.need_automatic_door):
        warnings.append(f"{chosen.name} has no automatic door opener.")
    if snap > config.DEST_ENTRANCE_SNAP_WARN_M:
        warnings.append(f"{chosen.name} is about {round(m_to_ft(snap), -1):.0f} ft from the nearest mapped path; "
                        "the first stretch may not be shown.")
    plan = OriginPlan(building_id=b.id, building_name=b.name, room=origin.room,
                      needs_elevator=origin.needs_elevator, can_reach_exit=can_reach_exit,
                      exit=chosen, exits=all_options, elevators=elevators, warnings=warnings)
    return OriginChoice(plan, node, snap, payload, fb_node, fb_snap)


def standard_exit(G, origin: Destination, active: list[Closure], onward: Onward, choice: OriginChoice) -> None:
    """Shortest route's exit: the open exit with the cheapest onward trip, steps allowed."""
    best = None
    for e, node, snap in open_doors(G, origin.building.entrances, active):
        res = onward(node)
        if res is not None and (best is None or res[0] < best[0]):
            best = (res[0], e, node, snap, res[2], res[1])
    if best is None:
        return
    _, e, node, snap, payload, length = best
    choice.standard_node, choice.standard_snap_m, choice.standard_payload = node, snap, payload
    choice.plan.standard_exit = door_option(e, length)
