"""Use drawing directions in a journey without manufacturing indoor meters.

Only explicitly source-matched coincident thresholds are supported here. A
nearby path is not a portal, and source review is not physical verification.
"""

from types import SimpleNamespace
from typing import Literal

from pydantic import Field, HttpUrl, model_validator
from shapely.geometry import Point

from .engine import RoutingError
from .models import ContractModel, Coordinate
from .plan_wayfinding import PlanWayfindingRequest, plan_directions


class DrawingPortal(ContractModel):
    id: str
    building_id: str
    indoor_node_id: str
    floor_id: str
    outdoor_node_id: int | str
    outdoor_approach_node_id: int | str
    position: Coordinate
    entrance_id: str
    plan_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_urls: list[HttpUrl] = Field(min_length=2)
    evidence: str = Field(min_length=30)
    keycard_required: bool
    step_free: Literal[True]
    door_type: Literal["automatic", "push-button", "manual", "unknown"]
    physical_verification: Literal[False] = False
    connection_type: Literal["coincident_source_threshold"] = "coincident_source_threshold"

    # A transition at an existing graph point, not a made-up walkway across a gap.
    @property
    def geometry(self):
        return [(self.position.lng, self.position.lat)] * 2

    @property
    def length_m(self):
        return 0.0

    @property
    def grade_percent(self):
        return None

    @property
    def width_m(self):
        return None

    @property
    def public_access(self):
        # Residence authorization is separately enforced by DrawingJourneyEngine.route.
        return True

    @property
    def asset_id(self):
        return self.entrance_id

    @property
    def source_id(self):
        return str(self.source_urls[0])


class DrawingPortalRegistry(ContractModel):
    version: Literal[1] = 1
    portals: list[DrawingPortal] = Field(default_factory=list, max_length=100)
    unresolved: list[dict[str, str]] = Field(default_factory=list)
    generated_at: str | None = None
    source_observed_at: str | None = None
    source_fingerprints: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_portals(self):
        if len({p.id for p in self.portals}) != len(self.portals):
            raise ValueError("Duplicate portal IDs")
        return self


class DrawingJourneyEngine:
    """Adapter for journey composition; zero internal cost means unknown, never meters."""

    drawing_only = True

    def __init__(self, data, registry, request, outdoor):
        self.plan = data
        self.request = request
        self.nodes = {n.id: n for n in data.nodes}
        portals = [p for p in registry.portals if p.building_id == data.building_id]
        for portal in portals:
            node = self.nodes.get(portal.indoor_node_id)
            source = data.floor_sources.get(portal.floor_id, {})
            if (
                not node
                or (node.floor_id or data.floor_id) != portal.floor_id
                or source.get("sha256") != portal.plan_source_sha256
            ):
                raise RoutingError(
                    "portal_source_mismatch",
                    "Entrance match no longer agrees with the indoor source.",
                    409,
                )
            anchor = outdoor.graph.nodes.get(portal.outdoor_node_id)
            if not anchor or portal.outdoor_node_id not in outdoor.node_anchors:
                raise RoutingError(
                    "invalid_portal", "Entrance node is absent from this graph.", 409
                )
            gap = Point(outdoor.to_xy(anchor["lng"], anchor["lat"])).distance(
                Point(outdoor.to_xy(portal.position.lng, portal.position.lat))
            )
            if gap > 0.1:
                raise RoutingError(
                    "invalid_portal", "Entrance anchor moved; recheck its source.", 409
                )
            approach = outdoor.graph.get_edge_data(
                portal.outdoor_node_id, portal.outdoor_approach_node_id, default={}
            )
            if not any(edge.get("kind") == "path" for edge in approach.values()):
                raise RoutingError(
                    "invalid_portal",
                    "Reviewed outdoor approach is absent; recheck the portal.",
                    409,
                )
        self.data = SimpleNamespace(portals=portals, synthetic=False)

    def route(self, request, *, now=None):
        # Width/door requirements cannot be certified by these floor drawings.
        if request.min_width_m is not None or request.need_automatic_door:
            raise RoutingError(
                "drawing_preferences_unsupported",
                "Door operation and corridor widths are not verified in this "
                "drawing map; these requirements cannot be enforced.",
                409,
            )
        result = plan_directions(
            self.plan,
            PlanWayfindingRequest(
                start_node_id=request.start_node_id,
                end_node_id=request.end_node_id,
                accept_drawing_only=self.request.accept_drawing_only,
                resident_access_confirmed=self.request.resident_access_confirmed,
                closures=request.closures,
            ),
            now=now,
        )
        result["warnings"] = [
            w
            for w in result["warnings"]
            if not w.startswith("No geographic outdoor entrance connection")
        ]
        # These values participate only in known-metric candidate selection. They
        # are removed from returned drawing legs and totals by finalize_drawing_journey.
        return dict(result, total_distance=0.0, routing_cost=0.0, drawing_only=True)


def finalize_drawing_journey(result):
    drawing = any(leg.get("drawing_only") for leg in result["legs"])
    if not drawing:
        return result
    result["known_distance_m"] = result["total_distance"]
    result["total_distance"] = None
    result["routing_cost"] = None
    result["distance_complete"] = False
    result["physical_verification"] = False
    result["selection_basis"] = "Lowest known metric cost; indoor drawing distances are unknown."
    for leg in result["legs"]:
        if leg.get("drawing_only"):
            leg["total_distance"] = leg["routing_cost"] = None
    result["warnings"] = list(
        dict.fromkeys(
            [
                *result["warnings"],
                "This journey contains drawing-only indoor directions. Indoor distance, grade and "
                "current physical access are unknown; the total journey distance is unavailable.",
                "Source-matched entrances are not physical surveys. Confirm the signed door and "
                "permitted access on arrival.",
            ]
        )
    )
    return result
