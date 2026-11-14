"""Pydantic models: the shared request/response contracts (see docs/contracts.md)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from . import config


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class ClosureType(str, Enum):
    elevator_out = "elevator_out"
    construction = "construction"
    ramp_blocked = "ramp_blocked"
    path_closed = "path_closed"


# Backend (/closures, /official-reports, /community-reports) type names -> routing types.
BACKEND_TYPES = {
    "elevator": ClosureType.elevator_out.value,
    "ramp": ClosureType.ramp_blocked.value,
    "path": ClosureType.path_closed.value,
    "construction": ClosureType.construction.value,
}
# Backend field -> routing field. Routing names win if a payload has both.
BACKEND_FIELDS = {
    "lng": "lon",
    "radius": "radius_m",
    "start_time": "starts_at",
    "end_time": "expires_at",
    "last_confirmed": "confirmed_at",
}


class Closure(BaseModel):
    """An active problem reported on campus. Locate it by lat/lon (+ radius) or by edge_ids.

    Also accepts the backend's closure format (lat/lng, radius, type "elevator", start_time,
    end_time, last_confirmed, nested location). Unknown fields are ignored.
    """

    id: str
    type: ClosureType
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: float = Field(default=config.DEFAULT_CLOSURE_RADIUS_M, gt=0, le=500)
    edge_ids: Optional[list[str]] = Field(
        default=None, description='Explicit edges as "u_v" OSM node-id pairs (both directions blocked).'
    )
    description: Optional[str] = None
    reported_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    starts_at: Optional[datetime] = Field(default=None, description="Not active before this time")
    expires_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _from_backend_format(cls, data):
        if not isinstance(data, dict):
            return data
        d = dict(data)
        loc = d.get("location")
        if isinstance(loc, dict):
            d.setdefault("lat", loc.get("lat"))
            d.setdefault("lng", loc.get("lng", loc.get("lon")))
        for src, dst in BACKEND_FIELDS.items():
            if src in d:
                value = d.pop(src)
                d.setdefault(dst, value)
        if isinstance(d.get("type"), str):
            d["type"] = BACKEND_TYPES.get(d["type"], d["type"])
        if not d.get("description"):
            d["description"] = d.get("details") or d.get("title")
        return d

    @model_validator(mode="after")
    def _needs_location(self) -> "Closure":
        has_point = self.lat is not None and self.lon is not None
        if not has_point and not self.edge_ids:
            raise ValueError("closure needs lat+lon or edge_ids")
        return self


# ---------------------------------------------------------------------------
# Destination building (same shape as the backend's GET /buildings items)
# ---------------------------------------------------------------------------
class _AcceptsLon(BaseModel):
    """Backend uses `lng`; also accept `lon` so routing-style payloads work."""

    @model_validator(mode="before")
    @classmethod
    def _lon_to_lng(cls, data):
        if isinstance(data, dict) and "lng" not in data and "lon" in data:
            data = {**data, "lng": data["lon"]}
        return data


class DestinationEntrance(_AcceptsLon):
    id: Optional[str] = None
    name: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    step_free: bool
    hasAutoDoorOpener: Optional[bool] = None
    isAccessibleToAllFloors: Optional[bool] = None
    IsKeyCardRequired: Optional[bool] = None
    automatic_door: Optional[bool] = None
    door_type: Optional[str] = Field(default=None, description="automatic | push-button | manual (map UI)")

    @property
    def auto_door(self) -> Optional[bool]:
        if self.hasAutoDoorOpener is not None:
            return self.hasAutoDoorOpener
        if self.automatic_door is not None:
            return self.automatic_door
        if self.door_type:
            return self.door_type != "manual"
        return None


class DestinationElevator(_AcceptsLon):
    location: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    status: Optional[str] = Field(default=None, description='"out_of_service" counts as out')


class DoorIssue(BaseModel):
    """A broken automatic door opener near an entrance (doesn't block walkways)."""

    id: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=15.0, gt=0)
    closed: bool = Field(default=True, description="False = degraded (works intermittently)")
    description: Optional[str] = None


class DestinationBuilding(_AcceptsLon):
    id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    entrances: list[DestinationEntrance] = Field(default_factory=list)
    elevator_count: Optional[int] = Field(default=None, ge=0)
    elevators: list[DestinationElevator] = Field(default_factory=list)

    @property
    def total_elevators(self) -> int:
        return self.elevator_count if self.elevator_count is not None else len(self.elevators)


class Destination(BaseModel):
    """Route to the best entrance of this building instead of a fixed `end` point."""

    building: DestinationBuilding
    needs_elevator: bool = Field(
        default=False, description="True if the room is on a floor the user can only reach by elevator"
    )
    room: Optional[str] = Field(default=None, description="Echoed back; used by the indoor stage later")
    need_automatic_door: bool = Field(default=False, description="Prefer entrances with a working door opener")
    door_issues: list[DoorIssue] = Field(default_factory=list)


class RouteRequest(BaseModel):
    start: LatLon
    end: Optional[LatLon] = Field(default=None, description="Required unless `destination` is given")
    destination: Optional[Destination] = None
    max_grade_pct: float = Field(default=config.DEFAULT_MAX_GRADE_PCT, ge=0, le=config.MAX_GRADE_PCT_LIMIT)
    avoid_steps: bool = True
    include_standard: bool = True
    closures: list[Closure] = Field(default_factory=list)

    @model_validator(mode="after")
    def _needs_target(self) -> "RouteRequest":
        if self.end is None and self.destination is None:
            raise ValueError("give `end` or `destination`")
        return self


class Segment(BaseModel):
    edge_ids: list[str]
    kind: str  # path | steps | ramp | elevator | crossing
    name: Optional[str] = None
    length_m: float
    grade_pct: float = Field(description="Length-weighted signed grade (+ uphill in travel direction)")
    max_grade_pct: float = Field(description="Steepest absolute grade in this segment")
    step_count: Optional[int] = None
    bearing_deg: float
    instruction: str = Field(description="Template-generated directions text")
    geometry: dict[str, Any]  # GeoJSON LineString, [lon, lat]


class AppliedClosure(BaseModel):
    id: str
    type: ClosureType
    edges_blocked: int
    confirmed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    description: Optional[str] = None


class RouteResult(BaseModel):
    mode: str  # standard | accessible
    found: bool
    reason: Optional[str] = None
    distance_m: float = 0.0
    duration_s: float = 0.0
    max_grade_pct: float = 0.0
    step_count: int = 0
    steps_length_m: float = 0.0
    is_step_free: bool = True
    geometry: Optional[dict[str, Any]] = Field(default=None, description="GeoJSON Feature<LineString>")
    segments: list[Segment] = Field(default_factory=list)
    closures_applied: list[AppliedClosure] = Field(default_factory=list)
    last_confirmed_at: Optional[datetime] = Field(
        default=None, description="Most recent confirmation among closures that shaped this route"
    )


class SnapInfo(BaseModel):
    node_id: int
    lat: float
    lon: float
    snap_distance_m: float


class RouteMeta(BaseModel):
    compute_ms: float
    graph_nodes: int
    graph_edges: int
    max_grade_pct: float
    closures_received: int
    closures_active: int
    closures_expired: int
    closures_pending: int = 0
    start: SnapInfo
    end: SnapInfo


class EntranceOption(BaseModel):
    id: Optional[str] = None
    name: str
    lat: float
    lon: float
    step_free: bool
    usable: bool = Field(description="Step-free, not closed, and reachable under the grade limit")
    chosen: bool = False
    reasons: list[str] = Field(default_factory=list, description="Why it is unusable or ranked lower")
    route_distance_m: Optional[float] = None
    to_working_elevator_m: Optional[float] = Field(
        default=None, description="Straight-line estimate from this door to the nearest working elevator"
    )
    auto_door: Optional[bool] = None
    door_issue: Optional[str] = Field(default=None, description="Reported door-opener problem at this entrance")
    key_card_required: Optional[bool] = None
    accessible_to_all_floors: Optional[bool] = None


class ElevatorStatus(BaseModel):
    total: int
    possibly_out: int = Field(description="Elevators covered by an active elevator_out closure")
    working: int
    located: int = Field(description="How many elevators have coordinates")
    closure_ids: list[str] = Field(default_factory=list)
    last_confirmed_at: Optional[datetime] = None


class DestinationPlan(BaseModel):
    building_id: str
    building_name: str
    room: Optional[str] = None
    needs_elevator: bool
    upper_floors_reachable: bool = Field(description="A working elevator exists (by current closures)")
    entrance: Optional[EntranceOption] = Field(default=None, description="Where the accessible route ends")
    standard_entrance: Optional[EntranceOption] = Field(
        default=None, description="Where the standard route ends: nearest open entrance, steps allowed"
    )
    entrances: list[EntranceOption] = Field(default_factory=list)
    elevators: ElevatorStatus
    warnings: list[str] = Field(default_factory=list, description="Plain-language notes for the user")


class RouteResponse(BaseModel):
    accessible: RouteResult
    standard: Optional[RouteResult] = None
    destination: Optional[DestinationPlan] = None
    meta: RouteMeta


class HealthResponse(BaseModel):
    status: str
    graph_loaded: bool
    nodes: int = 0
    edges: int = 0
    graph_path: str
