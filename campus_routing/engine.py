"""Dijkstra over request-local edges, with metric geometry and exact edge selection."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import networkx as nx
from pyproj import Transformer
from shapely import STRtree, transform
from shapely.geometry import LineString, Point
from shapely.ops import substring

from .directions import walking_directions
from .graph import load_graph
from .models import Coordinate, RouteProperties, RouteRequest, RouteResponse
from .models import LineString as RouteLine


class RoutingError(Exception):
    def __init__(self, code: str, message: str, status: int = 404):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class RoutingEngine:
    def __init__(self, graph: nx.MultiDiGraph, max_snap_distance: float = 50):
        self.graph = nx.freeze(graph.copy())
        self.max_snap_distance = max_snap_distance
        # UMass Amherst is in UTM zone 18N. All distance/radius operations use meters.
        self.to_xy = Transformer.from_crs(4326, 32618, always_xy=True).transform
        self.to_lnglat = Transformer.from_crs(32618, 4326, always_xy=True).transform
        self.edge_ids = list(self.graph.edges(keys=True))
        self.lines = []
        self.node_anchors = {}
        for u, v, k in self.edge_ids:
            edge = self.graph[u][v][k]
            coords = edge.get("coordinates") or [
                (self.graph.nodes[n]["lng"], self.graph.nodes[n]["lat"]) for n in (u, v)
            ]
            # Geometry must run from u to v, including OSM reciprocal edges.
            origin = Point(self.to_xy(self.graph.nodes[u]["lng"], self.graph.nodes[u]["lat"]))
            line = transform(LineString(coords), self.to_xy, interleaved=False)
            if not line.is_valid or line.length <= 0:
                raise ValueError(f"Edge {(u, v, k)} has invalid or zero-length geometry")
            if origin.distance(Point(line.coords[-1])) < origin.distance(Point(line.coords[0])):
                line = LineString(list(line.coords)[::-1])
            self.lines.append(line)
            index = len(self.lines) - 1
            self.node_anchors.setdefault(u, (u, index, Point(line.coords[0]), 0.0))
            self.node_anchors.setdefault(v, (v, index, Point(line.coords[-1]), 0.0))
        self.tree = STRtree(self.lines)

    @classmethod
    def from_file(cls, path: str | Path):
        return cls(load_graph(Path(path)))

    def _snap(self, point: Coordinate, label: str):
        xy = Point(self.to_xy(point.lng, point.lat))
        index = int(self.tree.nearest(xy))
        line = self.lines[index]
        distance = xy.distance(line)
        if distance > self.max_snap_distance:
            raise RoutingError(
                "outside_coverage",
                f"{label} is {distance:.1f} m from the walking network; "
                f"choose a point within {self.max_snap_distance:g} m.",
                422,
            )
        projected = line.interpolate(line.project(xy))
        u, v, _ = self.edge_ids[index]
        if projected.distance(Point(line.coords[0])) < 0.01:
            node = u
            projected = Point(line.coords[0])
        elif projected.distance(Point(line.coords[-1])) < 0.01:
            node = v
            projected = Point(line.coords[-1])
        else:
            node = f"__{label}"
        return node, index, projected, distance

    def _closure_effects(self, request: RouteRequest, now: datetime):
        blocked, degraded, warnings = set(), set(), []
        for closure in request.closures:
            if closure.start_time > now or (closure.end_time and closure.end_time <= now):
                continue
            if closure.floor_id is not None:
                warnings.append(
                    "A floor-specific closure is handled by indoor routing, not the outdoor graph."
                )
                continue
            point = Point(self.to_xy(closure.lng, closure.lat))
            matches = []
            candidates = (
                [
                    i
                    for i, (u, v, k) in enumerate(self.edge_ids)
                    if self.graph[u][v][k].get("asset_id") == closure.asset_id
                ]
                if closure.asset_id
                else self.tree.query(point, predicate="dwithin", distance=closure.radius)
            )
            for i in candidates:
                i = int(i)
                u, v, k = self.edge_ids[i]
                edge_type = self.graph[u][v][k].get("kind", "path")
                if closure.type == "path" or edge_type == closure.type:
                    matches.append(i)
            if not matches:
                warnings.append(
                    f"An active {closure.type} closure at {closure.lat:.6f}, "
                    f"{closure.lng:.6f} could not be matched within {closure.radius:g} m; "
                    "its effect on the route is unknown."
                )
            (blocked if closure.status == "closed" else degraded).update(matches)
            if closure.last_confirmed is None or now - closure.last_confirmed > timedelta(hours=24):
                warnings.append("An active closure was last confirmed more than 24 hours ago.")
        return blocked, degraded, warnings

    def route(self, request: RouteRequest, *, now: datetime | None = None) -> RouteResponse:
        return self.route_many(request, [request.start], [request.end], now=now)[0]

    def route_many(
        self, request, starts, ends, *, now=None, start_node_ids=None, end_node_ids=None
    ):
        """One search over all entrance choices, without connecting crossing levels."""
        now = now or datetime.now(UTC)
        blocked, degraded, warnings = self._closure_effects(request, now)

        def snap_options(points, label, node_ids):
            options = []
            for index, point in enumerate(points):
                try:
                    bound = node_ids[index] if node_ids else None
                    if bound is not None:
                        anchor = self.node_anchors.get(bound)
                        if anchor is None:
                            raise RoutingError(
                                "unknown_graph_node", "Portal graph node is missing.", 422
                            )
                        distance = Point(self.to_xy(point.lng, point.lat)).distance(anchor[2])
                        if distance > 1:
                            raise RoutingError(
                                "invalid_portal", "Portal point does not match its graph node.", 422
                            )
                    else:
                        anchor = self._snap(point, f"{label}{index}")
                    options.append((index, anchor))
                except RoutingError:
                    if len(points) == 1:
                        raise
            if not options:
                raise RoutingError(
                    "outside_coverage", f"No {label} entrance is near the walking network.", 422
                )
            return options

        start_options = snap_options(starts, "start", start_node_ids)
        end_options = snap_options(ends, "end", end_node_ids)
        # Snap against the original graph, never across a closure to a nearby eligible path.
        splits = defaultdict(list)
        anchors = []
        for options in (start_options, end_options):
            for i, (index, anchor) in enumerate(options):
                equivalent = next(
                    (
                        a
                        for a in anchors
                        if a[2].distance(anchor[2]) < 0.001
                        and set(self.edge_ids[a[1]][:2]) == set(self.edge_ids[anchor[1]][:2])
                    ),
                    None,
                )
                if equivalent is not None:
                    anchor = (equivalent[0], *anchor[1:])
                    options[i] = (index, anchor)
                anchors.append(anchor)
        for node, index, point, _ in anchors:
            u, v, _ = self.edge_ids[index]
            if node in (u, v):
                continue
            # Split reciprocal/parallel representations of the SAME physical segment.
            # Crossing paths on different levels must never acquire a new connection.
            for i in self.tree.query(point, predicate="dwithin", distance=0.01):
                i = int(i)
                a, b, _ = self.edge_ids[i]
                if {a, b} == {u, v} and self.lines[i].equals(self.lines[index]):
                    splits[i].append((self.lines[i].project(point), node))

        search = nx.DiGraph()
        source_node, target_node = "__trip_source", "__trip_target"
        for index, anchor in start_options:
            if (
                not search.has_edge(source_node, anchor[0])
                or anchor[3] < search[source_node][anchor[0]]["cost"]
            ):
                search.add_edge(source_node, anchor[0], cost=anchor[3], option=index)
        for index, anchor in end_options:
            if (
                not search.has_edge(anchor[0], target_node)
                or anchor[3] < search[anchor[0]][target_node]["cost"]
            ):
                search.add_edge(anchor[0], target_node, cost=anchor[3], option=index)
        for i, (u, v, k) in enumerate(self.edge_ids):
            attrs = self.graph[u][v][k]
            grade = attrs.get("grade_percent")
            if i in blocked or (request.no_stairs and attrs.get("kind") == "steps"):
                continue
            if request.no_stairs and attrs.get("wheelchair") == "no":
                continue
            if attrs.get("access") in ("no", "private") or attrs.get("foot") == "no":
                continue
            if request.min_width_m is not None:
                if attrs.get("width_m") is None or attrs["width_m"] < request.min_width_m:
                    continue
            if request.max_grade is not None:
                if grade is None and not request.allow_unknown_grade:
                    continue
                if grade is not None and grade > request.max_grade:
                    continue
            line = self.lines[i]
            stops = [(0.0, u), *sorted(set(splits[i])), (line.length, v)]
            for (a, source), (b, target) in pairwise(stops):
                if source == target or b - a < 1e-9:
                    continue
                geometry = substring(line, a, b)
                length = attrs["length"] * (b - a) / line.length
                cost = length * (5 if i in degraded else 1)
                if not search.has_edge(source, target) or cost < search[source][target]["cost"]:
                    search.add_edge(
                        source,
                        target,
                        **{
                            **attrs,
                            "length": length,
                            "cost": cost,
                            "line": geometry,
                            "degraded": i in degraded,
                        },
                    )
        try:
            full_path = nx.shortest_path(
                search, source_node, target_node, weight="cost", method="dijkstra"
            )
        except nx.NetworkXNoPath as exc:
            raise RoutingError(
                "no_route",
                "No route satisfies these preferences and active closures. "
                "Missing slope data can also prevent a route; constraints were not relaxed.",
            ) from exc
        start_index = search[source_node][full_path[1]]["option"]
        end_index = search[full_path[-2]][target_node]["option"]
        start = dict(start_options)[start_index]
        end = dict(end_options)[end_index]
        path = full_path[1:-1]
        edges = [search[a][b] for a, b in pairwise(path)]
        coordinates = []
        for edge in edges:
            coords = list(transform(edge["line"], self.to_lnglat, interleaved=False).coords)
            coordinates.extend(coords if not coordinates else coords[1:])
        if not coordinates:
            coordinates = [self.to_lnglat(start[2].x, start[2].y)] * 2

        source = self.graph.graph.get("source", "unknown")
        if self.graph.graph.get("synthetic"):
            warnings.insert(
                0, "Synthetic demo graph: paths, elevators, and grades are not campus facts."
            )
        else:
            warnings.insert(
                0, "OSM accessibility tags may be incomplete; entrances are not field verified."
            )
        if any(edge.get("grade_source") == "dem" for edge in edges):
            warnings.append(
                "Grades are terrain estimates, not measurements of ramp or sidewalk surfaces."
            )
        unknown = any(edge.get("grade_percent") is None for edge in edges)
        if unknown:
            warnings.append(
                "Slope is unknown on part of this route; the maximum grade cannot be verified."
            )
        uses_stairs = any(edge.get("kind") == "steps" for edge in edges)
        uses_elevator = any(edge.get("kind") == "elevator" for edge in edges)
        if uses_stairs:
            warnings.append("This route includes stairs.")
        if uses_elevator:
            warnings.append("This route relies on an elevator; check its current operating status.")
        if any(edge["degraded"] for edge in edges):
            warnings.append("This route passes through an area reported as degraded.")
        for label, anchor in zip(("Start", "End"), (start, end), strict=True):
            if anchor[3] > 1:
                warnings.append(
                    f"{label} snapped {anchor[3]:.1f} m to a mapped path; "
                    "the connection from the pin is not verified or included in distance."
                )
        maneuvers = walking_directions(edges, self.to_lnglat, coordinates[-1])
        directions = [step["instruction"] for step in maneuvers]

        def coordinate(anchor):
            lng, lat = self.to_lnglat(anchor[2].x, anchor[2].y)
            return Coordinate(lat=lat, lng=lng)

        result = RouteResponse(
            geometry=RouteLine(coordinates=coordinates),
            properties=RouteProperties(
                total_distance=round(sum(edge["length"] for edge in edges), 2),
                max_grade=None
                if unknown
                else round(max((edge["grade_percent"] for edge in edges), default=0), 4),
                warnings=list(dict.fromkeys(warnings)),
                directions=directions,
                maneuvers=maneuvers,
                graph_source=source,
                uses_stairs=uses_stairs,
                uses_elevator=uses_elevator,
                snapped_start=coordinate(start),
                snapped_end=coordinate(end),
                start_snap_distance=round(start[3], 2),
                end_snap_distance=round(end[3], 2),
                routing_cost=round(sum(edge["cost"] for edge in edges), 2),
            ),
        )
        return result, start_index, end_index
