"""POST /api/route: the map UI's routing contract (role-2-map-ui, contracts/route.contract.json).

The frontend sends
    {start: {lat, lng}, end: {lat, lng}, preferences: UserPreferences, closures: Closure[]}
and expects
    {step_free: RouteResponse, shortest: RouteResponse}
where RouteResponse is a GeoJSON FeatureCollection with `summary`, `steps` and `profile`.

This module only translates. Pathfinding is the same `plan_routes` used by POST /route.

Preference mapping:
    max_grade_pct                    -> max grade (clamped to 0..30)
    no_stairs or wheelchair_required -> avoid stairs (default true)
    other preferences                -> not used by the engine yet (listed in meta.ignored_preferences)

Closure mapping (frontend Closure -> engine Closure):
    status "repaired"                -> dropped
    status "closed" or "degraded"    -> blocks (same "block by default" policy as SIN notices)
    type elevator/ramp/path/construction -> elevator_out/ramp_blocked/path_closed/construction
    type automatic_door              -> dropped (door openers affect entrances, not walkways)
    affects "road"                   -> dropped (vehicles only; sidewalks stay open)
    radius                           -> clamped to the engine's 500 m limit
A closure the engine can't read is skipped and listed in meta.skipped_closures; it never
fails the whole request.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import config
from .routing.pathfinding import plan_routes
from .schemas import Closure, Destination, RouteRequest, RouteResult
from .utils.geo import haversine_m

router = APIRouter()

RADIUS_LIMIT_M = 500.0
DROPPED_TYPES = {"automatic_door"}
SUPPORTED_PREFS = {"max_grade_pct", "no_stairs", "wheelchair_required", "mobility_preset"}


class Point(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    @model_validator(mode="before")
    @classmethod
    def _accept_lon(cls, d):
        if isinstance(d, dict) and "lng" not in d and "lon" in d:
            d = {**d, "lng": d["lon"]}
        return d


class FrontendDestination(BaseModel):
    """The destination building as the map UI holds it (its `Building` type), sent as-is."""

    model_config = ConfigDict(extra="ignore")
    building: dict[str, Any]
    needs_elevator: bool = False
    room: Optional[str] = None


class FrontendRouteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: Optional[Point] = None
    origin: Optional[FrontendDestination] = None  # start building: the engine picks the exit
    end: Optional[Point] = None
    destination: Optional[FrontendDestination] = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    closures: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _target(self) -> "FrontendRouteRequest":
        if self.end is None and self.destination is None:
            raise ValueError("give `end` or `destination`")
        if self.start is None and self.origin is None:
            raise ValueError("give `start` or `origin`")
        return self


# ------------------------------------------------------------------ inputs
def map_preferences(prefs: dict[str, Any]) -> tuple[float, bool, list[str]]:
    try:
        grade = float(prefs.get("max_grade_pct", config.DEFAULT_MAX_GRADE_PCT))
    except (TypeError, ValueError):
        grade = config.DEFAULT_MAX_GRADE_PCT
    grade = min(max(grade, 0.0), config.MAX_GRADE_PCT_LIMIT)
    avoid_steps = bool(prefs.get("no_stairs", True)) or bool(prefs.get("wheelchair_required", False))
    ignored = sorted(k for k, v in prefs.items() if k not in SUPPORTED_PREFS and v is True)
    return grade, avoid_steps, ignored


def map_closures(raw: list[dict[str, Any]]) -> tuple[list[Closure], list[dict[str, str]]]:
    kept: list[Closure] = []
    skipped: list[dict[str, str]] = []
    for c in raw:
        cid = str(c.get("id", "?"))
        if c.get("status") == "repaired":
            continue
        if c.get("type") in DROPPED_TYPES:
            skipped.append({"id": cid, "reason": f"type {c.get('type')} doesn't block walkways "
                                                  "(used only to choose a destination entrance)"})
            continue
        if c.get("affects") == "road":
            skipped.append({"id": cid, "reason": "affects roads only"})
            continue
        d = dict(c)
        d.pop("status", None)  # frontend statuses aren't the engine's
        if isinstance(d.get("radius"), (int, float)):
            d["radius"] = min(max(float(d["radius"]), 1.0), RADIUS_LIMIT_M)
        if not d.get("description"):
            d["description"] = d.get("title")
        try:
            kept.append(Closure.model_validate(d))
        except ValidationError as exc:
            skipped.append({"id": cid, "reason": exc.errors()[0].get("msg", "invalid")})
    return kept, skipped


def map_building(fb: dict[str, Any]) -> dict[str, Any]:
    """Map UI `Building` -> engine DestinationBuilding (backend `/buildings` items also work as-is)."""
    if "location" not in fb or "entrances" not in fb:
        return fb  # already in the backend / engine shape
    loc = fb.get("location") or {}
    entrances = [
        {
            "id": e.get("id"),
            "name": e.get("name") or e.get("id") or "Entrance",
            "lat": e.get("lat"),
            "lng": e.get("lng", e.get("lon")),
            "step_free": bool(e.get("step_free")),
            "door_type": e.get("door_type"),
        }
        for e in fb.get("entrances") or []
    ]
    el = fb.get("elevators") or {}
    if isinstance(el, list):  # backend shape inside a UI object
        el = {"list": el, "total_count": len(el)}
    items = [{"location": x.get("name") or x.get("id"), "status": x.get("status")} for x in el.get("list") or []]
    total = el.get("total_count")
    total = max(int(total) if isinstance(total, (int, float)) else 0, len(items))
    # Unlisted elevators (count says more than the list names) start as working.
    items += [{"location": "unspecified elevator", "status": None} for _ in range(total - len(items))]
    working = el.get("working_count")
    if el.get("status") == "all_down":
        working = 0
    if isinstance(working, (int, float)):
        # The counts can say more are down than the list marks; we can't tell which, so mark
        # unmarked ones out until the counts agree (only the number matters for routing).
        missing_out = (total - int(working)) - sum(1 for x in items if x["status"] == "out_of_service")
        for x in items:
            if missing_out <= 0:
                break
            if x["status"] != "out_of_service":
                x["status"] = "out_of_service"
                missing_out -= 1
    return {
        "id": str(fb.get("id") or fb.get("code") or "building"),
        "name": fb.get("name") or "Destination",
        "lat": loc.get("lat"),
        "lng": loc.get("lng", loc.get("lon")),
        "entrances": entrances,
        "elevator_count": total,
        "elevators": items,
    }


def door_issues(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map UI `automatic_door` closures -> engine door issues (they don't block walkways)."""
    out = []
    for c in raw:
        if c.get("type") != "automatic_door" or c.get("status") == "repaired":
            continue
        try:
            out.append({"id": str(c.get("id", "?")), "lat": float(c["lat"]), "lng": float(c["lng"]),
                        "radius_m": float(c.get("radius") or 15), "closed": c.get("status") != "degraded",
                        "description": c.get("title") or c.get("description")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ----------------------------------------------------------------- outputs
def _edge_nodes(edge_id: str) -> Optional[tuple[int, int]]:
    try:
        u, v = (int(x) for x in edge_id.split("_"))
        return u, v
    except ValueError:
        return None


def _icon(kind: str, instruction: str, grade: float, first: bool) -> str:
    if kind == "steps":
        return "stairs"
    if kind == "elevator":
        return "elevator"
    if kind == "crossing":
        return "crossing"
    if kind == "ramp":
        return "ramp-up" if grade >= 0 else "ramp-down"
    if first:
        return "start"
    text = instruction.lower()
    for side in ("left", "right"):
        if text.startswith(f"bear {side}"):
            return f"slight-{side}"
        if text.startswith("turn") and side in text.split(",")[0]:
            return f"turn-{side}"
    return "straight"


def to_frontend(G, r: RouteResult, closures: list[Closure], end: Point, grade_limit: float,
                arrive: Optional[str] = None) -> dict[str, Any]:
    """Engine RouteResult -> frontend RouteResponse (GeoJSON FeatureCollection)."""
    if not r.found:
        return {
            "type": "FeatureCollection",
            "found": False,
            "features": [],
            "steps": [],
            "summary": {
                "total_distance_m": 0, "total_duration_s": 0, "max_grade_pct": 0, "avg_grade_pct": 0,
                "elevation_gain_m": 0, "is_step_free": True, "stair_count": 0,
                "warnings": [r.reason or "No route found"],
            },
        }

    features, steps, profile = [], [], []
    dist = gain = abs_grade_len = 0.0
    stairs_segments = 0
    elevators_used: list[str] = []
    for i, s in enumerate(r.segments):
        coords = s.geometry["coordinates"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "grade": s.grade_pct,
                "surface": "unknown",
                "is_step": s.kind == "steps",
                "is_ramp": s.kind == "ramp",
                "is_elevator": s.kind == "elevator",
                "step_count": s.step_count,
                "segment_name": s.name or "",
            },
        })
        steps.append({
            "instruction": s.instruction,
            "distance_m": s.length_m,
            "grade_pct": s.grade_pct,
            "icon": _icon(s.kind, s.instruction, s.grade_pct, i == 0),
            "at": coords[0],
        })
        if s.kind == "steps":
            stairs_segments += 1
        if s.kind == "elevator":
            elevators_used.append(s.name or "elevator")
        if s.kind != "steps":
            abs_grade_len += abs(s.grade_pct) * s.length_m

        # Elevation profile and gain from the graph's node elevations.
        for eid in s.edge_ids:
            uv = _edge_nodes(eid)
            if not uv or uv[0] not in G or uv[1] not in G:
                continue
            zu, zv = G.nodes[uv[0]].get("elevation"), G.nodes[uv[1]].get("elevation")
            if zu is None or zv is None:
                continue
            if not profile:
                profile.append({"d": 0.0, "z": round(zu, 1)})
            data = min(G[uv[0]][uv[1]].values(), key=lambda d: d.get("length") or 0)
            dist += float(data.get("length") or 0)
            profile.append({"d": round(dist, 1), "z": round(zv, 1)})
            gain += max(0.0, zv - zu)

    last = features[-1]["geometry"]["coordinates"][-1]
    steps.append({"instruction": arrive or "Arrive at your destination", "distance_m": 0, "grade_pct": 0,
                  "icon": "destination", "at": last})

    by_id = {c.id: c for c in closures}
    avoided, warnings, closures_avoided = [], [], []
    for a in r.closures_applied:
        if not a.edges_blocked:
            continue
        closures_avoided.append(a.id)
        c = by_id.get(a.id)
        label = a.description or a.type.value.replace("_", " ")
        warnings.append(f"Rerouted around: {label}")
        if c is not None and c.lat is not None:
            avoided.append({"kind": "closure", "label": label, "at": [c.lon, c.lat]})
    if r.steps_length_m > 0:
        warnings.append(f"Includes about {round(r.steps_length_m)} m of stairs")
    # Accessible: warn as grades near the user's limit. Shortest: warn above it.
    threshold = max(grade_limit * (0.8 if r.mode == "accessible" else 1.0), 2.0)
    steep = sorted((s for s in r.segments if s.kind != "steps" and s.max_grade_pct >= threshold),
                   key=lambda s: -s.max_grade_pct)
    for s in steep[:2]:
        warnings.append(f"Steep stretch ({s.max_grade_pct:.1f}%) for {round(s.length_m)} m")
    end_gap = haversine_m(last[1], last[0], end.lat, end.lng)
    if end_gap > 30:
        warnings.append(f"Route ends {round(end_gap)} m from the requested point (nearest mapped path)")

    return {
        "type": "FeatureCollection",
        "found": True,
        "features": features,
        "steps": steps,
        "profile": profile,
        "avoided": avoided,
        "summary": {
            "total_distance_m": r.distance_m,
            "total_duration_s": r.duration_s,
            "max_grade_pct": r.max_grade_pct,
            "avg_grade_pct": round(abs_grade_len / r.distance_m, 1) if r.distance_m else 0.0,
            "elevation_gain_m": round(gain, 1),
            "is_step_free": r.is_step_free,
            # Steps counted where OSM tags them; otherwise the number of stair segments.
            "stair_count": r.step_count or stairs_segments,
            "warnings": warnings,
            "elevators_used": elevators_used,
            "closures_avoided": closures_avoided,
            "last_confirmed": r.last_confirmed_at.isoformat() if r.last_confirmed_at else None,
        },
    }


@router.post("/api/route")
def frontend_route(body: FrontendRouteRequest, request: Request) -> dict[str, Any]:
    G = request.app.state.graph
    if G is None:
        raise HTTPException(503, detail=f"graph not loaded: {request.app.state.graph_error}")
    grade, avoid_steps, ignored = map_preferences(body.preferences)
    closures, skipped = map_closures(body.closures)

    def building_block(fd: Optional[FrontendDestination], label: str) -> Optional[Destination]:
        if fd is None:
            return None
        try:
            return Destination.model_validate({
                "building": map_building(fd.building),
                "needs_elevator": fd.needs_elevator,
                "room": fd.room,
                "need_automatic_door": bool(body.preferences.get("need_automatic_door", False)),
                "door_issues": door_issues(body.closures),
            })
        except ValidationError as exc:
            raise HTTPException(422, detail=f"{label} building: {exc.errors()[0].get('msg')}")

    destination = building_block(body.destination, "destination")
    origin = building_block(body.origin, "origin")
    if destination is not None or origin is not None:
        ignored = [p for p in ignored if p != "need_automatic_door"]  # used for the door choice

    b, pad = config.BBOX, 0.002
    points = []
    if body.start is not None:
        points.append(("start", body.start.lat, body.start.lng))
    if origin is not None:
        points.append(("origin", origin.building.lat, origin.building.lng))
    if body.end is not None:
        points.append(("end", body.end.lat, body.end.lng))
    if destination is not None:
        points.append(("destination", destination.building.lat, destination.building.lng))
    for label, lat, lng in points:
        if not (b["south"] - pad <= lat <= b["north"] + pad and b["west"] - pad <= lng <= b["east"] + pad):
            raise HTTPException(422, detail=f"{label} is outside the supported campus area")

    req = RouteRequest(
        start={"lat": body.start.lat, "lon": body.start.lng} if body.start is not None else None,
        origin=origin,
        end=None if destination else {"lat": body.end.lat, "lon": body.end.lng},
        destination=destination,
        max_grade_pct=grade,
        avoid_steps=avoid_steps,
        include_standard=True,
        closures=closures,
    )
    resp = plan_routes(G, req)

    plan = resp.destination
    if plan is not None and plan.entrance is not None:
        target = Point(lat=plan.entrance.lat, lng=plan.entrance.lon)
    elif body.end is not None:
        target = body.end
    else:
        target = Point(lat=destination.building.lat, lng=destination.building.lng)
    arrive = f"Arrive at {plan.building_name}, {plan.entrance.name}" if plan and plan.entrance else None
    std_target, std_arrive = target, arrive
    if plan is not None and plan.standard_entrance is not None:
        std_target = Point(lat=plan.standard_entrance.lat, lng=plan.standard_entrance.lon)
        std_arrive = f"Arrive at {plan.building_name}, {plan.standard_entrance.name}"

    step_free = to_frontend(G, resp.accessible, closures, target, grade, arrive)
    shortest = to_frontend(G, resp.standard, closures, std_target, grade, std_arrive) if resp.standard else None
    oplan = resp.origin
    if oplan is not None:
        if oplan.exit is not None:
            depart = f"Leave {oplan.building_name} by the {oplan.exit.name}"
            if step_free["steps"]:
                step_free["steps"][0]["instruction"] = f"{depart}. " + step_free["steps"][0]["instruction"]
        if shortest and shortest["steps"] and oplan.standard_exit is not None:
            shortest["steps"][0]["instruction"] = (f"Leave {oplan.building_name} by the {oplan.standard_exit.name}. "
                                                   + shortest["steps"][0]["instruction"])
    moved_notes = []
    for label, s in (("Starting", resp.meta.start), ("Ending", resp.meta.end)):
        if label == "Starting" and oplan is not None:
            continue  # exits are doors; never moved
        if s.moved and step_free["found"]:
            moved_notes.append(f"{label} from the nearest path you can use, about "
                               f"{round(s.snap_distance_m)} m from the point you chose.")
    step_free["summary"]["warnings"] = moved_notes + step_free["summary"]["warnings"]
    plan_warnings = (oplan.warnings if oplan else []) + (plan.warnings if plan else [])
    if plan_warnings:
        # Elevator and door notes belong to the step-free trip; show them before the user sets off.
        merged = plan_warnings + step_free["summary"]["warnings"]
        if not step_free["found"]:
            merged = plan_warnings  # the plans already explain why; skip the generic reason
        step_free["summary"]["warnings"] = list(dict.fromkeys(merged))
    return {
        "step_free": step_free,
        "shortest": shortest,
        "origin": None if oplan is None else {
            **oplan.model_dump(mode="json"),
            "exit_id": oplan.exit.id if oplan.exit else None,
            "start": {"lat": oplan.exit.lat, "lng": oplan.exit.lon} if oplan.exit else None,
            "standard_exit_id": oplan.standard_exit.id if oplan.standard_exit else None,
            "standard_start": ({"lat": oplan.standard_exit.lat, "lng": oplan.standard_exit.lon}
                               if oplan.standard_exit else None),
        },
        "destination": None if plan is None else {
            **plan.model_dump(mode="json"),
            "entrance_id": plan.entrance.id if plan.entrance else None,
            "end": {"lat": target.lat, "lng": target.lng},
            "standard_entrance_id": plan.standard_entrance.id if plan.standard_entrance else None,
            "standard_end": {"lat": std_target.lat, "lng": std_target.lng},
        },
        "meta": {
            **resp.meta.model_dump(mode="json"),
            "max_grade_pct": grade,
            "avoid_steps": avoid_steps,
            "ignored_preferences": ignored,
            "skipped_closures": skipped,
        },
    }
