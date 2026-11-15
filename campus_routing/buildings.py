"""Source-backed buildings and entrance choices. No invented interior connections."""

import json
from pathlib import Path

from pydantic import Field

from .engine import RoutingError
from .entrance_observations import apply_door_observations, read_door_observations
from .models import Closure, ContractModel, Coordinate, RouteRequest


class Place(Coordinate):
    name: str = Field(default="Map pin", max_length=150)
    building_id: str | None = None
    entrance_id: str | None = None


class TripRequest(ContractModel):
    origin: Place
    destination: Place
    max_grade: float = Field(default=5, ge=0, le=100)
    no_stairs: bool = True
    need_automatic_door: bool = False
    allow_keycard_entrance_approach: bool = False
    prefer_indoor_entrance: bool = False
    closures: list[Closure] = Field(default_factory=list, max_length=500)


def read_buildings(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("buildings"), list) or not payload["buildings"]:
        raise ValueError("No building catalog")
    observations = read_door_observations(path.parent / "reviews/entrance-observations.json")
    return apply_door_observations(payload, observations) if observations else payload


def choices(place, catalog, *, step_free, automatic, allow_keycard_approach=False):
    if not place.building_id:
        return [{"id": None, "name": place.name, "lat": place.lat, "lng": place.lng}]
    building = next((b for b in catalog["buildings"] if b["id"] == place.building_id), None)
    if building is None:
        raise RoutingError("unknown_building", "This building is not in the campus catalog.", 422)
    if not building["in_routing_area"]:
        raise RoutingError(
            "outside_coverage", f"{building['name']} is outside the current walking graph.", 422
        )
    entrances = building["entrances"]
    if place.entrance_id:
        entrances = [e for e in entrances if e["id"] == place.entrance_id]
        if not entrances:
            raise RoutingError(
                "unknown_entrance", "The selected entrance does not belong to this building.", 422
            )
    usable = [
        e
        for e in entrances
        if (allow_keycard_approach or not e.get("keycard_required"))
        and e.get("in_routing_area", True)
        and (not step_free or e["step_free"] is not False)
    ]
    if not usable:
        raise RoutingError(
            "no_entrance",
            f"No mapped public entrance at {building['name']} matches these requirements.",
        )
    if automatic:
        powered = [e for e in usable if e["door_type"] in ("automatic", "push-button")]
        if not powered:
            raise RoutingError(
                "automatic_door_unconfirmed",
                f"Automatic doors are required, but none of the eligible mapped entrances "
                f"at {building['name']} has a documented automatic door or push-button opener. "
                "Door records may be incomplete; this does not establish that the building "
                "has no accessible entrance.",
            )
        return powered
    return usable


def plan_trip(engine, catalog, request, *, now=None):
    """Choose the shortest feasible outdoor approach across mapped entrance pairs."""
    notes = [
        "Routes end on the outdoor walking network. "
        "Indoor continuation requires an explicitly matched entrance.",
        "UMass entrance records are labeled August 2022; current door access may differ.",
    ]
    if request.allow_keycard_entrance_approach:
        notes.append(
            "Keycard entrance approaches are allowed for this outdoor trip. "
            "The route ends outside; resident access and permission to enter "
            "have not been established."
        )

    def best(step_free):
        starts = choices(
            request.origin,
            catalog,
            step_free=step_free and request.no_stairs,
            automatic=step_free and request.need_automatic_door,
            allow_keycard_approach=request.allow_keycard_entrance_approach,
        )
        ends = choices(
            request.destination,
            catalog,
            step_free=step_free and request.no_stairs,
            automatic=step_free and request.need_automatic_door,
            allow_keycard_approach=request.allow_keycard_entrance_approach,
        )
        a = [Coordinate(lat=p["lat"], lng=p["lng"]) for p in starts]
        b = [Coordinate(lat=p["lat"], lng=p["lng"]) for p in ends]
        try:
            result, si, ei = engine.route_many(
                RouteRequest(
                    start=a[0],
                    end=b[0],
                    max_grade=request.max_grade if step_free else None,
                    no_stairs=request.no_stairs if step_free else False,
                    allow_unknown_grade=False if step_free else True,
                    closures=request.closures,
                ),
                a,
                b,
                now=now,
            )
        except RoutingError as exc:
            if exc.code not in ("no_route", "outside_coverage"):
                raise
            return None
        return result, starts[si], ends[ei]

    failure = None
    failure_code = None
    try:
        accessible = best(True)
        if accessible is None:
            failure_code = "no_route"
            failure = (
                "No mapped route satisfies the selected entrances, slope limit, "
                "stairs preference, and active closures."
            )
    except RoutingError as exc:
        if exc.status == 422:
            raise
        accessible, failure = None, exc.message
        failure_code = exc.code
    try:
        standard = best(False)
    except RoutingError:
        standard = None
    if accessible:
        for label, entrance in zip(("Start", "Destination"), accessible[1:], strict=True):
            if entrance.get("source_record_date") or entrance.get("door_evidence"):
                notes.append(f"{label}: {entrance['notes']}")
            if entrance.get("approach_only"):
                notes.append(
                    f"{label}: outdoor meeting point only; the building entrance "
                    "and final door connection are not mapped."
                )
                continue
            if entrance.get("step_free") is None and entrance["id"]:
                notes.append(
                    f"{label}: {entrance['name']} has a mapped position, "
                    "but step-free door access is unverified."
                )
    return {
        "accessible": accessible[0] if accessible else None,
        "standard": standard[0] if standard else None,
        "start_entrance": accessible[1] if accessible else None,
        "end_entrance": accessible[2] if accessible else None,
        "notes": notes,
        "failure": failure,
        "failure_code": failure_code,
        "graph_edges": engine.graph.number_of_edges(),
    }
