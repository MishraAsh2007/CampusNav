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


class RouteRequest(BaseModel):
    start: LatLon
    end: LatLon
    max_grade_pct: float = Field(default=config.DEFAULT_MAX_GRADE_PCT, ge=0, le=config.MAX_GRADE_PCT_LIMIT)
    avoid_steps: bool = True
    include_standard: bool = True
    closures: list[Closure] = Field(default_factory=list)


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


class RouteResponse(BaseModel):
    accessible: RouteResult
    standard: Optional[RouteResult] = None
    meta: RouteMeta


class HealthResponse(BaseModel):
    status: str
    graph_loaded: bool
    nodes: int = 0
    edges: int = 0
    graph_path: str
