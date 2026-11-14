"""Floor-aware graph routing over explicitly mapped indoor connections.

Indoor x/y coordinates belong to their floor plan, never to the outdoor map CRS.
Two points at the same x/y on different floors have no connection unless an edge says so.
"""

import math
from datetime import UTC, datetime, timedelta
from itertools import groupby, pairwise
from pathlib import Path
from typing import Literal

import networkx as nx
from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from .engine import RoutingError
from .models import Closure, ContractModel, Coordinate


class IndoorSource(ContractModel):
    id: str = Field(min_length=1, max_length=150)
    url: HttpUrl
    edition: str
    observed_at: AwareDatetime


class Floor(ContractModel):
    id: str = Field(min_length=1, max_length=80)
    label: str
    coordinate_system: Literal["local_meters", "image_pixels"] = "local_meters"
    image_url: HttpUrl | None = None
    image_width: float | None = Field(default=None, gt=0)
    image_height: float | None = Field(default=None, gt=0)
    source_id: str
    aliases: list[str] = Field(default_factory=list, max_length=30)


class IndoorNode(ContractModel):
    id: str = Field(min_length=1, max_length=150)
    label: str
    floor_id: str
    kind: Literal["room", "entrance", "junction", "elevator_stop", "stair_landing"]
    x: float
    y: float
    position: Coordinate | None = None
    source_id: str
    aliases: list[str] = Field(default_factory=list, max_length=30)
    source_record_ids: list[str] = Field(default_factory=list, max_length=30)


class Maneuver(ContractModel):
    """Reviewed, direction-specific guidance: never inferred from a room number."""

    id: str
    from_node: str
    via_node: str
    to_node: str
    instruction: str = Field(min_length=5, max_length=500)
    source_id: str
    evidence: str = Field(min_length=10)


class IndoorEdge(ContractModel):
    id: str = Field(min_length=1, max_length=150)
    start: str
    end: str
    kind: Literal["corridor", "door", "ramp", "steps", "elevator"]
    length_m: float = Field(gt=0, le=10000)
    geometry: list[tuple[float, float]] | None = Field(default=None, min_length=2)
    asset_id: str | None = None
    bidirectional: bool = True
    public_access: bool
    step_free: bool | None
    grade_percent: float | None = Field(default=None, ge=0, le=100)
    width_m: float | None = Field(default=None, gt=0)
    door_type: Literal["automatic", "push-button", "manual", "unknown"] = "unknown"
    source_id: str
    evidence: str = Field(min_length=10)


class IndoorAsset(ContractModel):
    id: str = Field(min_length=1, max_length=150)
    label: str
    kind: Literal["elevator", "ramp", "path"]
    position: Coordinate | None = None
    source_id: str
    aliases: list[str] = Field(default_factory=list, max_length=30)


class Portal(ContractModel):
    """A reviewed path from an indoor entrance to an EXISTING outdoor graph node."""

    id: str
    indoor_node_id: str
    outdoor_node_id: int | str
    geometry: list[tuple[float, float]] = Field(min_length=2, description="WGS84 [lng, lat]")
    length_m: float = Field(gt=0)
    public_access: bool
    step_free: bool | None
    grade_percent: float | None = Field(default=None, ge=0, le=100)
    width_m: float | None = Field(default=None, gt=0)
    door_type: Literal["automatic", "push-button", "manual", "unknown"] = "unknown"
    asset_id: str | None = None
    source_id: str
    evidence: str = Field(min_length=10)

    @model_validator(mode="after")
    def coordinates_are_geographic(self):
        if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in self.geometry):
            raise ValueError("Portal geometry must be WGS84 longitude/latitude")
        return self


class IndoorMap(ContractModel):
    version: Literal[1] = 1
    building_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    name: str
    synthetic: bool = False
    status: Literal["draft", "reviewed"] = "draft"
    reviewed_at: AwareDatetime | None = None
    review_notes: str = ""
    sources: list[IndoorSource] = Field(min_length=1)
    floors: list[Floor] = Field(min_length=1)
    nodes: list[IndoorNode] = Field(default_factory=list, max_length=20000)
    assets: list[IndoorAsset] = Field(default_factory=list, max_length=1000)
    edges: list[IndoorEdge] = Field(default_factory=list, max_length=50000)
    portals: list[Portal] = Field(default_factory=list, max_length=30)
    maneuvers: list[Maneuver] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def topology(self):
        for rows in (
            self.sources,
            self.floors,
            self.nodes,
            self.assets,
            self.edges,
            self.portals,
            self.maneuvers,
        ):
            if len({x.id for x in rows}) != len(rows):
                raise ValueError("IDs must be unique within each collection")
        sources = {s.id for s in self.sources}
        floors = {f.id for f in self.floors}
        nodes = {n.id: n for n in self.nodes}
        assets = {a.id: a for a in self.assets}
        for row in [
            *self.floors,
            *self.nodes,
            *self.assets,
            *self.edges,
            *self.portals,
            *self.maneuvers,
        ]:
            if row.source_id not in sources:
                raise ValueError("Unknown source_id")
        for node in self.nodes:
            if node.floor_id not in floors:
                raise ValueError("Node references an unknown floor")
        for edge in self.edges:
            if edge.start not in nodes or edge.end not in nodes or edge.start == edge.end:
                raise ValueError("Edge must connect two existing, distinct nodes")
            a, b = nodes[edge.start], nodes[edge.end]
            vertical = a.floor_id != b.floor_id
            if vertical and edge.kind not in ("elevator", "steps", "ramp"):
                raise ValueError("Only explicit elevator, stairs or ramp edges can change floors")
            if edge.kind == "elevator":
                if not vertical or not edge.asset_id or assets.get(edge.asset_id) is None:
                    raise ValueError("Elevator edge requires distinct floors and a mapped asset")
                if assets[edge.asset_id].kind != "elevator":
                    raise ValueError("Elevator edge requires an elevator asset")
                if a.kind != "elevator_stop" or b.kind != "elevator_stop":
                    raise ValueError("Elevators connect explicitly identified elevator stops")
            if edge.asset_id and edge.asset_id not in assets:
                raise ValueError("Unknown edge asset_id")
            if vertical and edge.geometry is not None:
                raise ValueError("Floor transitions use stop points, not a line across floor plans")
            if not vertical:
                if (
                    not edge.geometry
                    or edge.geometry[0] != (a.x, a.y)
                    or edge.geometry[-1] != (b.x, b.y)
                ):
                    raise ValueError(
                        "Same-floor geometry must run from the start node to the end node"
                    )
        for portal in self.portals:
            node = nodes.get(portal.indoor_node_id)
            if not node or node.kind != "entrance" or node.position is None:
                raise ValueError("Portal requires an entrance with geographic position")
            if math.dist(portal.geometry[0], (node.position.lng, node.position.lat)) > 1e-7:
                raise ValueError("Portal must start at its entrance's geographic position")
            if portal.asset_id and portal.asset_id not in assets:
                raise ValueError("Unknown portal asset_id")
        directed = {(e.start, e.end) for e in self.edges} | {
            (e.end, e.start) for e in self.edges if e.bidirectional
        }
        seen_maneuvers = set()
        for cue in self.maneuvers:
            triple = (cue.from_node, cue.via_node, cue.to_node)
            if triple in seen_maneuvers or len(set(triple)) != 3:
                raise ValueError("Maneuvers require a unique three-node approach")
            seen_maneuvers.add(triple)
            if (cue.from_node, cue.via_node) not in directed or (
                cue.via_node,
                cue.to_node,
            ) not in directed:
                raise ValueError("Maneuver must reference two connected directed edges")
            if nodes[cue.via_node].floor_id != nodes[cue.to_node].floor_id:
                raise ValueError("A maneuver cannot replace a floor-transition instruction")
        if self.status == "reviewed":
            if not self.reviewed_at or len(self.review_notes.strip()) < 10 or not self.edges:
                raise ValueError("Reviewed maps require timestamp, review notes and mapped edges")
        return self


class IndoorPreferences(ContractModel):
    max_grade: float | None = Field(default=5, ge=0, le=100)
    no_stairs: bool = True
    allow_unknown_access: bool = False
    allow_unknown_grade: bool = False
    need_automatic_door: bool = False
    min_width_m: float | None = Field(default=None, gt=0, le=5)


class IndoorRouteRequest(IndoorPreferences):
    building_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    start_node_id: str
    end_node_id: str
    closures: list[Closure] = Field(default_factory=list, max_length=500)


def eligible(edge, prefs):
    if not edge.public_access:
        return False
    kind = getattr(edge, "kind", "door")
    if prefs.no_stairs:
        if kind == "steps" or edge.step_free is False:
            return False
        if edge.step_free is None and not prefs.allow_unknown_access:
            return False
    # A vertical elevator ride is not a walking grade.
    if kind not in ("elevator", "steps") and prefs.max_grade is not None:
        if edge.grade_percent is None and not prefs.allow_unknown_grade:
            return False
        if edge.grade_percent is not None and edge.grade_percent > prefs.max_grade:
            return False
    if prefs.need_automatic_door and kind == "door":
        if edge.door_type not in ("automatic", "push-button"):
            return False
    if prefs.min_width_m is not None:
        if getattr(edge, "width_m", None) is None or edge.width_m < prefs.min_width_m:
            return False
    return True


class IndoorEngine:
    def __init__(self, data: IndoorMap, *, allow_synthetic=False):
        self.data = data
        if data.status != "reviewed":
            raise RoutingError("indoor_not_ready", "Indoor topology is still awaiting review.", 409)
        if data.synthetic and not allow_synthetic:
            raise RoutingError(
                "synthetic_indoor_map", "Demo maps cannot serve production routes.", 409
            )
        self.nodes = {n.id: n for n in data.nodes}
        self.floors = {f.id: f for f in data.floors}
        self.assets = {a.id: a for a in data.assets}

    def closure_effects(self, closures, now):
        effects, warnings = {}, []
        for c in closures:
            if c.start_time > now or (c.end_time and c.end_time <= now):
                continue
            if c.building_id and c.building_id != self.data.building_id:
                continue
            matches = []
            if c.asset_id:
                if c.asset_id in self.assets:
                    matches = [
                        e.id
                        for e in self.data.edges
                        if e.asset_id == c.asset_id
                        and (
                            not c.floor_id
                            or c.floor_id
                            in (self.nodes[e.start].floor_id, self.nodes[e.end].floor_id)
                        )
                        and (c.type == "path" or e.kind == c.type)
                    ]
                elif c.building_id == self.data.building_id:
                    warnings.append(f"Closure asset {c.asset_id} is not mapped in this building.")
            elif c.building_id == self.data.building_id and c.floor_id:
                # Geographic matching is allowed only on an explicit building+floor.
                scale = math.cos(math.radians(c.lat))

                def xy(p, closure=c, longitude_scale=scale):
                    return (
                        (p.lng - closure.lng) * 111320 * longitude_scale,
                        (p.lat - closure.lat) * 111320,
                    )

                for e in self.data.edges:
                    a, b = self.nodes[e.start], self.nodes[e.end]
                    if a.floor_id != c.floor_id or b.floor_id != c.floor_id:
                        continue
                    # Endpoints alone cannot establish the corridor's geographic geometry.
                    # Match a located asset, rather than inventing a straight corridor.
                    asset = self.assets.get(e.asset_id)
                    if asset and asset.position and math.hypot(*xy(asset.position)) <= c.radius:
                        if c.type == "path" or e.kind == c.type:
                            matches.append(e.id)
            elif c.building_id == self.data.building_id:
                warnings.append(
                    "An indoor closure has no asset or floor scope; its effect is unknown."
                )
            for ident in matches:
                effects[ident] = max(effects.get(ident, 1), math.inf if c.status == "closed" else 5)
            if matches and now - c.last_confirmed > timedelta(hours=24):
                warnings.append("An indoor closure was confirmed more than 24 hours ago.")
            if not matches and c.building_id == self.data.building_id:
                warnings.append(
                    "An active indoor closure could not be matched; coverage is incomplete."
                )
        return effects, list(dict.fromkeys(warnings))

    def route(self, request: IndoorRouteRequest, *, now=None):
        if request.building_id != self.data.building_id:
            raise RoutingError("unknown_building", "Indoor map does not match the request.", 422)
        if request.start_node_id not in self.nodes or request.end_node_id not in self.nodes:
            raise RoutingError(
                "unknown_indoor_node", "Select a mapped room, entrance or landing.", 422
            )
        now = now or datetime.now(UTC)
        effects, warnings = self.closure_effects(request.closures, now)
        graph = nx.DiGraph()
        graph.add_nodes_from(self.nodes)
        for e in self.data.edges:
            factor = effects.get(e.id, 1)
            if not eligible(e, request) or math.isinf(factor):
                continue
            cost = e.length_m * factor
            for a, b, reverse in [(e.start, e.end, False)] + (
                [(e.end, e.start, True)] if e.bidirectional else []
            ):
                if not graph.has_edge(a, b) or cost < graph[a][b]["weight"]:
                    graph.add_edge(a, b, weight=cost, edge=e, reverse=reverse, degraded=factor > 1)
        try:
            path = nx.shortest_path(
                graph, request.start_node_id, request.end_node_id, weight="weight"
            )
        except nx.NetworkXNoPath as exc:
            raise RoutingError(
                "no_indoor_route", "No indoor route meets these preferences and closures."
            ) from exc
        segments, transitions, used, directions, steps = [], [], [], [], []
        cues = {(c.from_node, c.via_node, c.to_node): c for c in self.data.maneuvers}
        for index, (a_id, b_id) in enumerate(pairwise(path)):
            attrs = graph[a_id][b_id]
            e, a, b = attrs["edge"], self.nodes[a_id], self.nodes[b_id]
            used.append(e)
            record = dict(
                edge_id=e.id,
                kind=e.kind,
                asset_id=e.asset_id,
                distance_m=e.length_m,
                from_floor=a.floor_id,
                to_floor=b.floor_id,
                from_node_id=a.id,
                to_node_id=b.id,
                from_label=a.label,
                to_label=b.label,
                source_id=e.source_id,
                degraded=attrs["degraded"],
            )
            steps.append(record)
            if a.floor_id != b.floor_id:
                record.update(from_position=[a.x, a.y], to_position=[b.x, b.y])
                transitions.append(record)
                directions.append(
                    f"Use {self.assets[e.asset_id].label if e.asset_id else e.kind} "
                    f"from {self.floors[a.floor_id].label} to {self.floors[b.floor_id].label}."
                )
            else:
                record.update(
                    floor_id=a.floor_id,
                    coordinate_system=self.floors[a.floor_id].coordinate_system,
                    geometry={
                        "type": "LineString",
                        "coordinates": list(reversed(e.geometry))
                        if attrs["reverse"]
                        else e.geometry,
                    },
                )
                segments.append(record)
                directions.append(
                    f"Continue {e.length_m:g} m to {b.label} on {self.floors[b.floor_id].label}."
                )
            cue = cues.get((path[index - 1], a_id, b_id)) if index else None
            if cue:
                directions[-1] = cue.instruction
                record.update(maneuver_id=cue.id, instruction_source_id=cue.source_id)
            record["instruction"] = directions[-1]
        if self.data.synthetic:
            warnings.insert(0, "Synthetic indoor demonstration; this is not a campus floor plan.")
        warnings.append("Indoor routing uses the published map review; current access can change.")
        if any(e.step_free is None for e in used):
            warnings.append("Step-free access is unknown on part of this indoor route.")
        walking = [e for e in used if e.kind != "elevator"]
        if any(e.grade_percent is None for e in walking):
            warnings.append("Walking grade is unknown on part of this indoor route.")
        if any(e.kind == "elevator" for e in used):
            warnings.append(
                "This route relies on an elevator; "
                "absence of an outage is not operating confirmation."
            )
        if any(self.nodes[node_id].kind == "room" for node_id in path):
            warnings.append(
                "Room destination uses a pilot waypoint; verify the doorway and "
                "final approach on site."
            )
        return dict(
            building_id=self.data.building_id,
            synthetic=self.data.synthetic,
            node_path=path,
            floor_sequence=[floor for floor, _ in groupby(self.nodes[n].floor_id for n in path)],
            segments=segments,
            steps=steps,
            transitions=transitions,
            directions=directions,
            total_distance=round(sum(e.length_m for e in used), 2),
            routing_cost=round(sum(graph[a][b]["weight"] for a, b in pairwise(path)), 2),
            max_grade=None
            if any(e.grade_percent is None for e in walking)
            else max((e.grade_percent for e in walking), default=0),
            uses_stairs=any(e.kind == "steps" for e in used),
            uses_elevator=any(e.kind == "elevator" for e in used),
            warnings=warnings,
            reviewed_at=self.data.reviewed_at.isoformat(),
        )


def read_indoor(path: Path):
    return IndoorMap.model_validate_json(path.read_text(encoding="utf-8"))
