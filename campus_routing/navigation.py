"""Stateless guided navigation: clarify, leave, walk, confirm arrival, continue indoors."""

from datetime import UTC, datetime

from pydantic import Field

from .engine import RoutingError
from .indoor import IndoorEngine, IndoorPreferences
from .journey import JourneyRequest, plan_journey
from .models import Closure
from .places import LocationQuery


class NavigationRequest(IndoorPreferences):
    origin: LocationQuery | None = None
    origin_entrance_id: str | None = Field(default=None, max_length=150)
    destination: LocationQuery | None = None
    closures: list[Closure] | None = Field(default=None, max_length=500)


class ArrivalRequest(IndoorPreferences):
    building_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    portal_id: str = Field(max_length=150)
    confirmed: bool = False
    continue_indoors: bool | None = None
    destination: LocationQuery | None = None
    closures: list[Closure] | None = Field(default=None, max_length=500)


def stages(journey):
    result = []
    for index, leg in enumerate(journey["legs"]):
        if leg["kind"] == "outdoor":
            phase, instructions = "outdoor", leg["route"]["properties"]["directions"]
        elif leg["kind"] == "portal":
            phase = "leave_building" if leg["direction"] == "exit" else "enter_building"
            instructions = [leg["instruction"]]
        else:
            phase = (
                "leave_building"
                if any(
                    x["kind"] == "portal" and x["direction"] == "exit"
                    for x in journey["legs"][index + 1 :]
                )
                else "inside_destination"
            )
            instructions = leg["directions"]
        if leg["kind"] == "indoor" and not leg["steps"]:
            continue
        result.append(
            dict(id=f"stage-{index + 1}", phase=phase, instructions=instructions, leg=leg)
        )
    return result


class NavigationService:
    def __init__(self, outdoor, resolver, closure_provider):
        self.outdoor = outdoor
        self.resolver = resolver
        self.closure_provider = closure_provider

    def engine(self, building):
        data = self.resolver.maps.get(building)
        if data is None:
            raise RoutingError("indoor_not_mapped", "This building's interior is not mapped.", 409)
        return IndoorEngine(data, allow_synthetic=self.resolver.allow_synthetic)

    def closure_context(self, request):
        if request.closures is not None:
            return request.closures, dict(mode="request", count=len(request.closures))
        rows, metadata = self.closure_provider()
        return [Closure.model_validate(c) for c in rows], dict(mode="server_snapshot", **metadata)

    def route(self, origin, destination, prefs, closures, now):
        return plan_journey(
            self.outdoor,
            self.engine,
            JourneyRequest(
                origin=origin,
                destination=destination,
                closures=closures,
                **prefs,
            ),
            now=now,
        )

    @staticmethod
    def problem(exc):
        if exc.status >= 500:
            raise exc
        return dict(
            status="coverage_unavailable"
            if exc.code
            in (
                "indoor_not_mapped",
                "indoor_not_ready",
                "synthetic_indoor_map",
                "invalid_portal",
            )
            else "no_route",
            code=exc.code,
            message=exc.message,
        )

    @staticmethod
    def ready(journey, context):
        if context.get("stale"):
            journey["warnings"].append("The server's closure snapshot is stale.")
        return dict(
            status="route_ready",
            journey=journey,
            stages=stages(journey),
            closure_context=context,
            position_tracking="User-confirmed locations; no indoor GPS.",
        )

    def plan(self, request, *, now=None):
        now = now or datetime.now(UTC)
        start = self.resolver.resolve(request.origin, purpose="origin")
        if start["status"] != "resolved":
            return start
        end = self.resolver.resolve(request.destination, purpose="destination", allow_building=True)
        if end["status"] != "resolved":
            return end
        origin, destination = start["endpoint"], end["endpoint"]
        prefs = {key: getattr(request, key) for key in IndoorPreferences.model_fields}
        if destination["kind"] != "building":
            closures, context = self.closure_context(request)
            try:
                journey = self.route(origin, destination, prefs, closures, now)
                response = self.ready(journey, context)
                entrance = next((leg for leg in journey["legs"] if leg["kind"] == "portal"
                                 and leg["direction"] == "enter"), None)
                if entrance is not None:
                    response.update(arrival_context={"building_id": entrance["building_id"],
                                                     "portal_id": entrance["portal_id"]},
                                    arrival_confirmation_required=True)
                return response
            except RoutingError as exc:
                return self.problem(exc)
        building = destination["building_id"]
        if origin["kind"] == "indoor" and origin["building_id"] == building:
            return dict(
                status="needs_input",
                code="already_in_destination_building",
                field="destination.node_id",
                question="You are already in this building. Which room do you want to reach?",
            )
        try:
            inside = self.engine(building)
        except RoutingError as exc:
            return self.problem(exc)
        closures, context = self.closure_context(request)
        candidates = []
        for portal in inside.data.portals:
            try:
                journey = self.route(
                    origin,
                    dict(
                        kind="indoor",
                        building_id=building,
                        node_id=portal.indoor_node_id,
                        portal_id=portal.id,
                    ),
                    prefs,
                    closures,
                    now,
                )
            except RoutingError as exc:
                if exc.code in ("no_journey", "no_route", "outside_coverage"):
                    continue
                return self.problem(exc)
            # This first trip ends OUTSIDE. Do not tell the user they crossed a door.
            # Binding portal_id ensures these are precisely the final two legs.
            entrance_leg = journey["legs"][-2]
            if entrance_leg["kind"] != "portal" or entrance_leg["portal_id"] != portal.id:
                raise RoutingError("invalid_portal", "Arrival entrance could not be bound.", 409)
            journey["legs"] = journey["legs"][:-2]
            journey["total_distance"] = round(journey["total_distance"] - portal.length_m, 2)
            journey["routing_cost"] = round(
                journey["routing_cost"] - portal.length_m * (5 if entrance_leg["degraded"] else 1),
                2,
            )
            journey["scope"] = "to_outside_entrance_approach"
            candidates.append((journey, portal))
        if not candidates:
            return dict(
                status="no_route",
                code="no_journey",
                message="No complete route to a reviewed entrance meets these preferences "
                "and closures. No stairs or access requirements were relaxed.",
            )
        journey, portal = min(candidates, key=lambda pair: pair[0]["routing_cost"])
        response = self.ready(journey, context)
        response.update(
            arrival_context=dict(building_id=building, portal_id=portal.id),
            arrival_confirmation_required=True,
            on_arrival=dict(
                question=f"Do you need to go somewhere inside {inside.data.name}?",
                choices=[
                    dict(continue_indoors=True, label="Choose an indoor destination"),
                    dict(continue_indoors=False, label="Finish outside"),
                ],
            ),
        )
        return response

    def arrive(self, request, *, now=None):
        now = now or datetime.now(UTC)
        if request.building_id not in self.resolver.buildings:
            raise RoutingError("unsupported_building", "Choose a building in the catalog.", 422)
        try:
            engine = self.engine(request.building_id)
        except RoutingError as exc:
            return self.problem(exc)
        portal = next((p for p in engine.data.portals if p.id == request.portal_id), None)
        if portal is None:
            raise RoutingError("unknown_portal", "Select the entrance returned by navigation.", 422)
        label = engine.nodes[portal.indoor_node_id].label
        if not request.confirmed:
            return dict(
                status="needs_input",
                code="confirm_arrival",
                field="confirmed",
                question=f"Are you at the mapped outside approach to {label}?",
                choices=[dict(confirmed=True, label="I am here")],
            )
        if request.continue_indoors is None:
            return dict(
                status="needs_input",
                code="choose_indoor_destination",
                field="continue_indoors",
                question=f"Do you need to go somewhere inside {engine.data.name}?",
                choices=[
                    dict(continue_indoors=True, label="Choose a room or place"),
                    dict(continue_indoors=False, label="Finish outside"),
                ],
            )
        if not request.continue_indoors:
            return dict(
                status="arrived",
                scope="outside_entrance_approach",
                message=f"Finished outside {label}.",
            )
        query = request.destination or LocationQuery()
        if not query.building_id:
            query = query.model_copy(update={"building_id": request.building_id})
        end = self.resolver.resolve(query, purpose="destination")
        if end["status"] != "resolved":
            return end
        if end["endpoint"]["kind"] != "indoor" or (
            end["endpoint"]["building_id"] != request.building_id
        ):
            raise RoutingError("wrong_building", "Choose a destination inside this building.", 422)
        if portal.outdoor_node_id not in self.outdoor.graph:
            raise RoutingError(
                "invalid_portal", "Entrance references a different outdoor graph.", 409
            )
        node = self.outdoor.graph.nodes[portal.outdoor_node_id]
        origin = dict(
            kind="outdoor", lat=node["lat"], lng=node["lng"], graph_node_id=portal.outdoor_node_id
        )
        closures, context = self.closure_context(request)
        prefs = {key: getattr(request, key) for key in IndoorPreferences.model_fields}
        try:
            # Recompute from the confirmed outside position, including the approach and
            # current closures. A newly blocked entry may require another entrance.
            journey = self.route(origin, end["endpoint"], prefs, closures, now)
        except RoutingError as exc:
            return self.problem(exc)
        response = self.ready(journey, context)
        replacement = next((leg for leg in journey["legs"] if leg["kind"] == "portal"
                            and leg["direction"] == "enter" and leg["portal_id"] != portal.id), None)
        if replacement is not None:
            response.update(arrival_context={"building_id": request.building_id,
                                             "portal_id": replacement["portal_id"]},
                            arrival_confirmation_required=True)
        return response
