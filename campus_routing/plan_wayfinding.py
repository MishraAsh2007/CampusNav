"""Qualitative same-floor directions from a reviewed drawing, without invented meters.

This is deliberately separate from measured, access-verified indoor routing.
"""

from datetime import UTC, datetime
from itertools import pairwise
from typing import Literal

import networkx as nx
from pydantic import Field, model_validator

from .engine import RoutingError
from .models import Closure, ContractModel


class PlanNode(ContractModel):
    id: str
    label: str
    x: float | None = Field(default=None, ge=0)
    y: float | None = Field(default=None, ge=0)
    floor_id: str | None = None


class PlanConnection(ContractModel):
    id: str
    start: str
    end: str
    kind: Literal["door", "corridor", "elevator"]
    evidence: str = Field(min_length=10)
    asset_id: str
    served_floor_evidence: str | None = None
    forward_instruction: str | None = None
    reverse_instruction: str | None = None


class PlanWayfindingMap(ContractModel):
    building_id: str
    floor_id: str | None = None
    floor_sources: dict[str, dict[str, str]] = Field(default_factory=dict)
    source_url: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    drawing_review: str = Field(min_length=20)
    physical_verification: Literal[False] = False
    coordinate_system: Literal["pdf_points", "image_pixels", "landmarks_only"] = "pdf_points"
    resident_access_required: bool = True
    source_warnings: list[str] = Field(default_factory=list)
    nodes: list[PlanNode]
    connections: list[PlanConnection]

    @model_validator(mode="after")
    def connected_ids(self):
        if self.coordinate_system != "landmarks_only" and any(
            n.x is None or n.y is None for n in self.nodes
        ):
            raise ValueError("Drawing nodes require coordinates")
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes) or len({e.id for e in self.connections}) != len(
            self.connections
        ):
            raise ValueError("Duplicate node/connection IDs")
        for e in self.connections:
            if e.start not in ids or e.end not in ids or e.start == e.end:
                raise ValueError("Connections require distinct existing nodes")
            nodes = {n.id: n for n in self.nodes}
            a = nodes[e.start].floor_id or self.floor_id
            b = nodes[e.end].floor_id or self.floor_id
            if not a or not b:
                raise ValueError("Each node needs a floor")
            if a != b and e.kind != "elevator":
                raise ValueError("Only explicit elevator connections may change floors")
            if e.kind == "elevator" and (a == b or len(e.served_floor_evidence or "") < 20):
                raise ValueError("Elevator requires distinct documented floor stops")
        if self.floor_sources and any(
            (n.floor_id or self.floor_id) not in self.floor_sources for n in self.nodes
        ):
            raise ValueError("Missing floor source")
        return self


class PlanWayfindingRequest(ContractModel):
    start_node_id: str
    end_node_id: str
    accept_drawing_only: bool = False
    resident_access_confirmed: bool = False
    closures: list[Closure] = Field(default_factory=list, max_length=500)


def plan_directions(data, request, *, now=None):
    if not request.accept_drawing_only:
        raise RoutingError(
            "physical_verification_missing",
            "Only drawing-based directions exist here. "
            "Verified accessible navigation is unavailable.",
            409,
        )
    if data.resident_access_required and not request.resident_access_confirmed:
        raise RoutingError(
            "resident_access_required",
            "Confirm you are permitted to use the residence interior. "
            "This is not an access credential.",
            409,
        )
    nodes = {n.id: n for n in data.nodes}
    if request.start_node_id not in nodes or request.end_node_id not in nodes:
        raise RoutingError("unknown_plan_node", "Choose a destination in this floor map.", 422)
    now = now or datetime.now(UTC)
    active = [
        c
        for c in request.closures
        if c.start_time <= now
        and (c.end_time is None or c.end_time > now)
        and (not c.building_id or c.building_id == data.building_id)
    ]
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    for e in data.connections:
        edge_floors = {nodes[n].floor_id or data.floor_id for n in [e.start, e.end]}
        if any(
            c.asset_id == e.asset_id
            and c.status == "closed"
            and (not c.floor_id or c.floor_id in edge_floors)
            for c in active
        ):
            continue
        # Connection count is a topological preference, not metric distance.
        degraded = any(
            c.asset_id == e.asset_id
            and c.status == "degraded"
            and (not c.floor_id or c.floor_id in edge_floors)
            for c in active
        )
        graph.add_edge(e.start, e.end, connection=e, weight=5 if degraded else 1)
    try:
        path = nx.shortest_path(graph, request.start_node_id, request.end_node_id, weight="weight")
    except nx.NetworkXNoPath as error:
        raise RoutingError(
            "no_plan_path", "No drawing connection remains under these closures."
        ) from error
    steps = []
    for a, b in pairwise(path):
        e = graph[a][b]["connection"]
        from_floor = nodes[a].floor_id or data.floor_id
        to_floor = nodes[b].floor_id or data.floor_id
        custom = e.forward_instruction if e.start == a else e.reverse_instruction
        steps.append(
            dict(
                connection_id=e.id,
                kind=e.kind,
                asset_id=e.asset_id,
                from_node_id=a,
                to_node_id=b,
                instruction=custom
                or (
                    f"Use the mapped elevator bank from floor {from_floor} to floor {to_floor}. "
                    "Exit at the mapped lobby landing."
                    if e.kind == "elevator"
                    else (
                        "Pass through the doorway to "
                        if e.kind == "door"
                        else "Follow the hall to "
                    )
                    + nodes[b].label
                    + "."
                ),
                from_floor=from_floor,
                to_floor=to_floor,
                geometry=None
                if e.kind == "elevator" or data.coordinate_system == "landmarks_only"
                else [[nodes[a].x, nodes[a].y], [nodes[b].x, nodes[b].y]],
                from_position=None if nodes[a].x is None else [nodes[a].x, nodes[a].y],
                to_position=None if nodes[b].x is None else [nodes[b].x, nodes[b].y],
                evidence=e.evidence,
            )
        )
    instructions = []
    for step in steps:
        previous = instructions[-1] if instructions else None
        if (
            previous
            and step["kind"] == previous["kind"] == "elevator"
            and previous["asset_id"] == step["asset_id"]
            and previous["to_node_id"] == step["from_node_id"]
        ):
            previous.setdefault("connection_ids", [previous["connection_id"]]).append(
                step["connection_id"]
            )
            for key in ["to_node_id", "to_floor", "to_position"]:
                previous[key] = step[key]
            previous["instruction"] = (
                f"Use the mapped elevator bank from floor {previous['from_floor']} "
                f"to floor {previous['to_floor']}. "
                "Remain in the elevator until the destination floor."
            )
            previous["evidence"] += " " + step["evidence"]
        else:
            instructions.append(dict(step))
    return dict(
        building_id=data.building_id,
        floor_id=data.floor_id,
        scope="multi_floor_drawing_wayfinding"
        if any(s["kind"] == "elevator" for s in steps)
        else "same_floor_drawing_wayfinding",
        physical_verification=False,
        coordinate_system=data.coordinate_system,
        distance_m=None,
        max_grade=None,
        source_url=data.source_url,
        steps=instructions,
        graph_steps=steps,
        warnings=[
            *data.source_warnings,
            "Drawing-based directions only; current access, grades, widths "
            "and thresholds are unknown.",
            "No geographic outdoor entrance connection is included. "
            "Any elevator step depends on the documented stops and current operation.",
            "Only explicitly matched asset closures can block these drawing connections.",
        ],
    )
