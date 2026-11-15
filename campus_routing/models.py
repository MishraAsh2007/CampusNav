"""The wire contract. Distances are meters; grades are percentages (5 means 5%)."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Coordinate(ContractModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Closure(Coordinate):
    # Metadata added by Role 4 (Mongo IDs, descriptions) does not affect routing.
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    radius: float = Field(gt=0, le=1000, description="Affected radius in meters")
    type: Literal["elevator", "ramp", "path"]
    status: Literal["closed", "degraded"]
    source: Literal["official", "community", "verified"]
    start_time: AwareDatetime
    end_time: AwareDatetime | None
    last_confirmed: AwareDatetime | None
    asset_id: str | None = Field(default=None, max_length=150)
    building_id: str | None = Field(default=None, max_length=100)
    floor_id: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def check_interval(self):
        if self.floor_id is not None and not self.building_id:
            raise ValueError("floor_id requires building_id")
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class RouteRequest(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start": {"lat": 42.391, "lng": -72.528},
                    "end": {"lat": 42.392, "lng": -72.528},
                    "max_grade": 5,
                    "no_stairs": True,
                    "allow_unknown_grade": False,
                    "closures": [],
                }
            ]
        }
    )
    start: Coordinate
    end: Coordinate
    max_grade: float | None = Field(default=5, ge=0, le=100, description="null disables limit")
    no_stairs: bool = True
    allow_unknown_grade: bool = False
    min_width_m: float | None = Field(default=None, gt=0, le=5)
    closures: list[Closure] = Field(default_factory=list, max_length=500)


class LineString(ContractModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]] = Field(
        min_length=2, description="[longitude, latitude]"
    )


class RouteManeuver(ContractModel):
    instruction: str
    maneuver: Literal[
        "depart",
        "straight",
        "left",
        "right",
        "slight-left",
        "slight-right",
        "sharp-left",
        "sharp-right",
        "u-turn",
        "stairs",
        "ramp",
        "elevator",
        "arrive",
    ]
    distance_m: float = Field(ge=0)
    at: tuple[float, float] = Field(description="[longitude, latitude] at the maneuver")
    geometry: list[tuple[float, float]] = Field(min_length=2)
    grade_pct: float | None = Field(ge=0)


class RouteProperties(ContractModel):
    total_distance: float = Field(ge=0, description="Network distance in meters")
    max_grade: float | None = Field(ge=0, description="null if any route segment has unknown grade")
    warnings: list[str]
    directions: list[str]
    maneuvers: list[RouteManeuver] = Field(default_factory=list)
    graph_source: str
    uses_stairs: bool
    uses_elevator: bool
    snapped_start: Coordinate
    snapped_end: Coordinate
    start_snap_distance: float = Field(ge=0)
    end_snap_distance: float = Field(ge=0)
    routing_cost: float = Field(
        default=0, ge=0, description="Search cost including degraded-edge penalties"
    )


class RouteResponse(ContractModel):
    type: Literal["Feature"] = "Feature"
    geometry: LineString
    properties: RouteProperties
