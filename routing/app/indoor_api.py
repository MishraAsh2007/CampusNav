"""POST /api/indoor-route: the second stage, from a building entrance to a room or floor.

The outdoor stage (POST /api/route with a destination building) picks the entrance. The map UI
then sends that entrance here, with the same closures, once the user asks for indoor directions.

Request
    {building_id: "ilc",                          // id or name; aliases from indoor_overrides.json
     building: {...},                             // optional: the map UI / backend building, for elevator flags
     entrance: {lat, lng},                        // optional: the door the outdoor route ended at
     room: "N151" | floor: "5th floor",           // or node_id
     preferences: {step_free: true},              // default true
     closures: [...]}                             // same list as /api/route

Response (HTTP 200 for every outcome; check `status`)
    status: ok | no_route | not_found | not_public | no_map
    on ok: entrance, destination, total_m, steps[], legs[], elevators[], warnings[]
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .frontend_api import map_building, map_closures
from .indoor import router as ir
from .routing.closures import is_active
from .schemas import DestinationBuilding
from .utils.geo import m_to_ft

router = APIRouter()


class IndoorPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class IndoorRouteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    building_id: str
    building_name: Optional[str] = None
    building: Optional[dict[str, Any]] = None
    entrance: Optional[IndoorPoint] = None
    exit: Optional[IndoorPoint] = None      # with direction "to_exit": the door to leave through
    direction: Literal["to_room", "to_exit"] = "to_room"
    room: Optional[str] = None
    floor: Optional[str] = None
    node_id: Optional[str] = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    closures: list[dict[str, Any]] = Field(default_factory=list)


def _door_json(d: ir.Door, model: ir.Model) -> dict[str, Any]:
    return {"id": d.id, "name": d.name, "floor": d.floor, "floor_label": ir._floor_label(model, d.floor),
            "lat": d.lat, "lng": d.lng, "step_free_approach": d.step_free, "verified": d.verified}


def _elevators_json(model: ir.Model) -> list[dict[str, Any]]:
    return [{"id": b.asset_id, "label": b.label, "cars": b.car_ids, "usable": b.usable}
            for b in model.banks.values()]


@router.post("/api/indoor-route")
def indoor_route(body: IndoorRouteRequest) -> dict[str, Any]:
    key, m = ir.find_map(body.building_id, body.building_name)
    if m is None or not m.get("nodes"):
        return {"status": "no_map", "building_id": body.building_id,
                "message": "No indoor map for this building yet."}

    closures, skipped = map_closures(body.closures)
    active = [c for c in closures if is_active(c)]
    building = None
    if body.building:
        try:
            building = DestinationBuilding.model_validate(map_building(body.building))
        except ValidationError:
            building = None
    avoid_steps = bool(body.preferences.get("step_free", body.preferences.get("avoid_steps", True)))
    model = ir.build_model(key, m, active, avoid_steps, building)
    name = m.get("name", key)
    warnings: list[str] = []

    dest, msg = ir.resolve_destination(model, body.room, body.floor, body.node_id)
    if dest is None:
        return {"status": "not_found", "building": name, "message": msg}
    if msg:
        warnings.append(msg)
    nonpublic = (model.ov.get("non_public_floors") or {}).get(dest["floor_id"])
    if nonpublic:
        return {"status": "not_public", "building": name,
                "message": f"{ir._floor_label(model, dest['floor_id'])} of {name} isn't open to visitors. {nonpublic}"}

    leaving = body.direction == "to_exit"
    point = (body.exit or body.entrance) if leaving else body.entrance
    door = None
    if point is not None:
        door = ir._match_door(model, point.lat, point.lng)
        if door is None:
            warnings.append(f"That {'exit' if leaving else 'entrance'} isn't on the indoor map; using the best door instead.")
    found = ir.find_route(model, dest["id"], door)
    if found is None and door is not None:
        # The chosen door may be wrong for this destination (e.g. it only reaches a floor with its elevator out).
        alt = ir.find_route(model, dest["id"], None)
        if alt is not None:
            warnings.append(f"No indoor route {'to' if leaving else 'from'} {door.name}; using {alt.door.name} instead.")
            found = alt

    if found is None:
        reason = "No step-free indoor route found."
        healthy = ir.build_model(key, m, [], avoid_steps, building)
        if ir.find_route(healthy, dest["id"], None) is not None:
            down = [b.label for b in model.banks.values() if not b.usable]
            reason = (f"{ir._floor_label(model, dest['floor_id'])} is only reachable by elevator, and "
                      f"{', '.join(down) or 'the elevators'} may be out of service right now.")
        elif avoid_steps and ir.find_route(ir.build_model(key, m, [], False, building), dest["id"], None):
            reason = "The indoor map shows no step-free way to that place."
        return {"status": "no_route", "building": name, "destination": _dest_json(model, dest),
                "message": reason, "elevators": _elevators_json(model), "warnings": warnings}

    if leaving:
        found = ir.Found(found.door, list(reversed(found.path)), found.total_m)
    legs, steps = ir.build_legs(model, found, dest, reverse=leaving)
    d = found.door
    if d.step_free is None or d.verified == "partial":
        warnings.append(f"The {d.name} hasn't been checked for a step-free approach.")
    for b in model.banks.values():
        if not b.usable:
            warnings.append(f"{b.label} may be out of service; this route avoids it.")
    st = model.assessment.status
    if st.unattributed_out and any(b.usable for b in model.banks.values()):
        warnings.append("A report says an elevator is out but not which one; the route uses a bank that still has a working car either way.")
    floor = model.floors.get(dest["floor_id"], {})
    if not floor.get("image_url"):
        warnings.append(f"There is no floor plan for {floor.get('label', dest['floor_id'])} yet; its layout here is a placeholder.")
    for sk in skipped:
        warnings.append(f"Ignored closure {sk['id']}: {sk['reason']}")

    return {
        "status": "ok",
        "building": name,
        "exit" if leaving else "entrance": _door_json(d, model),
        "destination": _dest_json(model, dest),
        "total_m": round(found.total_m, 1),
        "total_ft": round(m_to_ft(found.total_m)),
        "steps": steps,
        "legs": legs,
        "elevators": _elevators_json(model),
        "warnings": warnings,
        "meta": {"direction": body.direction, "map_status": m.get("status"), "approximate": True, "step_free": avoid_steps,
                 "elevator_count_source": st.count_source, "elevators_out_unknown": st.unattributed_out},
    }


def _dest_json(model: ir.Model, n: dict[str, Any]) -> dict[str, Any]:
    return {"id": n["id"], "label": n["label"], "floor": n["floor_id"],
            "floor_label": ir._floor_label(model, n["floor_id"])}
