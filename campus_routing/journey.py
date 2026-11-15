"""Combine indoor legs with the outdoor graph only through reviewed entrance portals."""

import math
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field
from shapely.geometry import LineString, Point

from .engine import RoutingError
from .indoor import IndoorPreferences, IndoorRouteRequest, eligible
from .models import Closure, ContractModel, Coordinate, RouteRequest


class OutdoorEndpoint(Coordinate):
    kind: Literal["outdoor"]
    graph_node_id: int | str | None = None


class IndoorEndpoint(ContractModel):
    kind: Literal["indoor"]
    building_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    node_id: str
    portal_id: str | None = None


Endpoint = Annotated[OutdoorEndpoint | IndoorEndpoint, Field(discriminator="kind")]


class JourneyRequest(IndoorPreferences):
    origin: Endpoint
    destination: Endpoint
    closures: list[Closure] = Field(default_factory=list, max_length=500)


def plan_journey(outdoor, get_indoor, request, *, now=None):
    now = now or datetime.now(UTC)
    prefs = {k: getattr(request, k) for k in IndoorPreferences.model_fields}
    engines = {}
    for endpoint in (request.origin, request.destination):
        if endpoint.kind == "indoor":
            if endpoint.building_id not in engines:
                engines[endpoint.building_id] = get_indoor(endpoint.building_id)
            engine = engines[endpoint.building_id]
            if endpoint.node_id not in engine.nodes:
                raise RoutingError(
                    "unknown_indoor_node", "The indoor destination is not mapped.", 422
                )
            if endpoint.portal_id and endpoint.portal_id not in {p.id for p in engine.data.portals}:
                raise RoutingError("unknown_portal", "This entrance connection is not mapped.", 422)

    def indoor_leg(endpoint, start, end):
        return engines[endpoint.building_id].route(
            IndoorRouteRequest(
                building_id=endpoint.building_id,
                start_node_id=start,
                end_node_id=end,
                closures=request.closures,
                **prefs,
            ),
            now=now,
        )

    def options(endpoint, departing):
        if endpoint.kind == "outdoor":
            return [
                dict(
                    point=Coordinate(lat=endpoint.lat, lng=endpoint.lng),
                    node_id=endpoint.graph_node_id,
                    legs=[],
                    cost=0,
                    distance=0,
                    warnings=[],
                )
            ]
        engine = engines[endpoint.building_id]
        result = []
        for portal in engine.data.portals:
            if endpoint.portal_id and portal.id != endpoint.portal_id:
                continue
            if not eligible(portal, request):
                continue
            if portal.outdoor_node_id not in outdoor.graph:
                raise RoutingError(
                    "invalid_portal", "Indoor portal references a different outdoor graph.", 409
                )
            attrs = outdoor.graph.nodes[portal.outdoor_node_id]
            point = Coordinate(lat=attrs["lat"], lng=attrs["lng"])
            line = LineString([outdoor.to_xy(x, y) for x, y in portal.geometry])
            if Point(outdoor.to_xy(point.lng, point.lat)).distance(Point(line.coords[-1])) > 1:
                raise RoutingError(
                    "invalid_portal", "Portal geometry does not reach its outdoor node.", 409
                )
            floor = engine.nodes[portal.indoor_node_id].floor_id
            factor = 1
            for c in request.closures:
                if c.start_time > now or (c.end_time and c.end_time <= now):
                    continue
                if c.building_id and c.building_id != endpoint.building_id:
                    continue
                if c.floor_id and c.floor_id != floor:
                    continue
                if c.type != "path":
                    continue
                matched = (
                    portal.asset_id == c.asset_id
                    if c.asset_id
                    else (line.distance(Point(outdoor.to_xy(c.lng, c.lat))) <= c.radius)
                )
                if matched:
                    factor = max(factor, math.inf if c.status == "closed" else 5)
            if math.isinf(factor):
                continue
            start, end = (
                (endpoint.node_id, portal.indoor_node_id)
                if departing
                else (portal.indoor_node_id, endpoint.node_id)
            )
            try:
                inside = indoor_leg(endpoint, start, end)
            except RoutingError as exc:
                if exc.code == "no_indoor_route":
                    continue
                raise
            portal_leg = dict(
                kind="portal",
                portal_id=portal.id,
                building_id=endpoint.building_id,
                floor_id=floor,
                indoor_node_id=portal.indoor_node_id,
                entrance_label=engine.nodes[portal.indoor_node_id].label,
                direction="exit" if departing else "enter",
                instruction=("Exit via " if departing else "Enter via ")
                + engine.nodes[portal.indoor_node_id].label
                + ".",
                coordinate_system="WGS84",
                total_distance=portal.length_m,
                geometry={
                    "type": "LineString",
                    "coordinates": portal.geometry
                    if departing
                    else list(reversed(portal.geometry)),
                },
                source_id=portal.source_id,
                degraded=factor > 1,
                max_grade=portal.grade_percent,
            )
            inner_leg = dict(kind="indoor", **inside)
            result.append(
                dict(
                    point=point,
                    node_id=portal.outdoor_node_id,
                    legs=[inner_leg, portal_leg] if departing else [portal_leg, inner_leg],
                    cost=inside["routing_cost"] + portal.length_m * factor,
                    distance=inside["total_distance"] + portal.length_m,
                    warnings=inside["warnings"],
                )
            )
        return result

    candidates = []
    if (
        request.origin.kind == request.destination.kind == "indoor"
        and request.origin.building_id == request.destination.building_id
        and not request.origin.portal_id
        and not request.destination.portal_id
    ):
        try:
            leg = indoor_leg(request.origin, request.origin.node_id, request.destination.node_id)
            candidates.append(
                dict(
                    legs=[dict(kind="indoor", **leg)],
                    total_distance=leg["total_distance"],
                    routing_cost=leg["routing_cost"],
                    warnings=leg["warnings"],
                )
            )
        except RoutingError as exc:
            if exc.code != "no_indoor_route":
                raise
    starts, ends = options(request.origin, True), options(request.destination, False)
    # Indoor portals are few. Comparing full journey cost avoids choosing a short outdoor
    # leg that forces a long/infeasible indoor approach. Cache each indoor leg above.
    for a in starts:
        for b in ends:
            req = RouteRequest(
                start=a["point"],
                end=b["point"],
                max_grade=request.max_grade,
                no_stairs=request.no_stairs,
                allow_unknown_grade=request.allow_unknown_grade,
                min_width_m=request.min_width_m,
                closures=request.closures,
            )
            try:
                route = outdoor.route_many(
                    req,
                    [a["point"]],
                    [b["point"]],
                    now=now,
                    start_node_ids=[a["node_id"]],
                    end_node_ids=[b["node_id"]],
                )[0]
            except RoutingError as exc:
                if exc.code in ("no_route", "outside_coverage"):
                    continue
                raise
            p = route.properties
            candidates.append(
                dict(
                    legs=[
                        *a["legs"],
                        dict(kind="outdoor", route=route.model_dump(mode="json")),
                        *b["legs"],
                    ],
                    total_distance=round(a["distance"] + p.total_distance + b["distance"], 2),
                    routing_cost=round(
                        a["cost"]
                        + p.routing_cost
                        + b["cost"]
                        + p.start_snap_distance
                        + p.end_snap_distance,
                        2,
                    ),
                    warnings=[*a["warnings"], *p.warnings, *b["warnings"]],
                )
            )
    if not candidates:
        raise RoutingError(
            "no_journey",
            "No complete journey is mapped under these preferences and closures. "
            "Check indoor connections, portal coverage and elevator status.",
        )
    result = min(candidates, key=lambda c: c["routing_cost"])
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["synthetic"] = outdoor.graph.graph.get("synthetic", False) or any(
        e.data.synthetic for e in engines.values()
    )
    result["complete"] = True
    return result
