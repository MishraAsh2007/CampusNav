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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import backend_client, config
from .frontend_api import map_building, map_closures
from .indoor import overrides
from .indoor import router as ir
from .indoor import schematic
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
    closures: Optional[list[dict[str, Any]]] = None  # omitted: read the backend's GET /closures


def model_ov_aliases(key: str) -> list[str]:
    return list((overrides.load().get(key) or {}).get("aliases", []))


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

    raw_closures, closures_source, _ = backend_client.get_closures(body.closures)
    closures, skipped = map_closures(raw_closures)
    active = [c for c in closures if is_active(c)]
    building = None
    if not body.building:
        aliases = [a for a in (model_ov_aliases(key)) if " " not in a]
        found, _ = backend_client.get_building(body.building_id, key, *aliases)
        body.building = found
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
    if dest.get("approximate") and not dest.get("unmapped"):
        warnings.append(f"{dest['label']}'s exact spot on its floor isn't surveyed; the walking distance is approximate.")
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
    also = tuple(dest.get("alternatives") or ())
    found = ir.find_route(model, dest["id"], door, also)
    if found is None and door is not None:
        # The chosen door may be wrong for this destination (e.g. it only reaches a floor with its elevator out).
        alt = ir.find_route(model, dest["id"], None, also)
        if alt is not None:
            warnings.append(f"No indoor route {'to' if leaving else 'from'} {door.name}; using {alt.door.name} instead.")
            found = alt

    if found is None:
        reason = "No step-free indoor route found."
        healthy = ir.build_model(key, m, [], avoid_steps, building)
        if ir.find_route(healthy, dest["id"], None, also) is not None:
            down = [b.label for b in model.banks.values() if not b.usable]
            reason = (f"{ir._floor_label(model, dest['floor_id'])} is only reachable by elevator, and "
                      f"{', '.join(down) or 'the elevators'} may be out of service right now.")
        elif avoid_steps and ir.find_route(ir.build_model(key, m, [], False, building), dest["id"], None, also):
            reason = "The indoor map shows no step-free way to that place."
        return {"status": "no_route", "building": name, "destination": _dest_json(model, dest),
                "message": reason, "elevators": _elevators_json(model), "warnings": warnings}

    if leaving:
        found = ir.Found(found.door, list(reversed(found.path)), found.total_m)
    room_end = found.path[0] if leaving else found.path[-1]
    if found.path and room_end != dest["id"]:  # the nearer of several same-named places
        dest = model.nodes[room_end]
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
    if closures_source == "unavailable":
        warnings.append("Live closure data is unavailable, so elevator outages aren't reflected.")
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
        "node_path": found.path,
        "edge_ids": [ir.edge_id(model, a, b) for a, b in zip(found.path, found.path[1:])],
        "elevators": _elevators_json(model),
        "warnings": warnings,
        "meta": {"closures_source": closures_source, "direction": body.direction, "map_status": m.get("status"), "approximate": True, "step_free": avoid_steps,
                 "elevator_count_source": st.count_source, "elevators_out_unknown": st.unattributed_out},
    }


def _dest_json(model: ir.Model, n: dict[str, Any]) -> dict[str, Any]:
    return {"id": n["id"], "label": n["label"], "floor": n["floor_id"],
            "floor_label": ir._floor_label(model, n["floor_id"])}

# ------------------------------------------------------------------ map export for viewers
# The map UI's indoor viewer loads maps from GET /indoor/status and GET /indoor/maps/{id} (the
# campus_routing contract). Serving the same paths lets it show this engine's map (traced floors,
# real plan images) and draw the routes POST /api/indoor-route returns, matched by node and edge id.

def _plan_file(key: str, floor_id: str):
    p = config.INDOOR_PLANS_DIR / key / f"{floor_id}.png"
    return p if p.is_file() else None


@router.get("/api/indoor-plan/{building_id}/{floor_id}.svg")
def indoor_plan_svg(building_id: str, floor_id: str):
    """Clean schematic of a traced floor (footprint, hallways, rooms, elevators, doors)."""
    key, m = ir.find_map(building_id)
    svg = schematic.render(ir.build_model(key, m, [], False, None), floor_id) if key else None
    if svg is None:
        raise HTTPException(404, detail="No schematic plan for that building and floor.")
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


@router.get("/api/indoor-plan/{building_id}/{floor_id}.png")
def indoor_plan(building_id: str, floor_id: str):
    key, m = ir.find_map(building_id)
    p = _plan_file(key, floor_id) if key else None
    if p is None:
        raise HTTPException(404, detail="No floor-plan image for that building and floor.")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/indoor/status")
def indoor_status() -> dict[str, Any]:
    out = []
    for key, m in ir.load_maps().items():
        model = ir.build_model(key, m, [], False, None)
        routable = bool(model.doors) and any(n["kind"] == "room" for n in model.nodes.values())
        out.append({"building_id": key, "name": m.get("name", key), "routable": routable, "status": "engine",
                    "floors": len(model.floors)})
    return {"buildings": out, "router": "campusnav-routing"}


@router.get("/indoor/maps/{building_id}")
def indoor_map(building_id: str, request: Request) -> dict[str, Any]:
    key, m = ir.find_map(building_id)
    if m is None:
        raise HTTPException(404, detail="No indoor map for this building.")
    def plan_url(fid: str) -> Optional[str]:
        # Prefer the clean schematic; fall back to the raw plan image.
        if schematic.outline_file(key, fid) and fid in (overrides.load().get(key, {}).get("traced_floors") or {}):
            return f"/api/indoor-plan/{key}/{fid}.svg"
        return f"/api/indoor-plan/{key}/{fid}.png" if _plan_file(key, fid) else None

    return ir.export_map(ir.build_model(key, m, [], False, None), str(request.base_url).rstrip("/"), plan_url)
