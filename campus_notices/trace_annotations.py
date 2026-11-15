"""Draft drawing annotations with unknown measurements, kept outside routing maps."""

import math
from typing import Literal

from pydantic import Field, model_validator

from campus_routing.models import ContractModel


class PlanTrace(ContractModel):
    id: str
    source_id: str
    page: int = Field(ge=1)
    floors: list[str] = Field(min_length=1)
    kind: Literal["corridor", "suite_approach", "door", "elevator_candidate"]
    points: list[tuple[float, float]] = Field(min_length=2)
    coordinate_system: Literal["render_pixels", "pdf_points"]
    length_m: float | None = Field(default=None, gt=0)
    measurement_evidence: str | None = None
    access: Literal["unknown", "public", "resident_only", "staff_only"] = "unknown"
    evidence: str = Field(min_length=10)
    status: Literal["candidate", "reviewed"] = "candidate"

    @model_validator(mode="after")
    def measurements_need_evidence(self):
        if any(not all(math.isfinite(v) and v >= 0 for v in p) for p in self.points):
            raise ValueError("Trace points must be finite drawing coordinates")
        if self.length_m is not None and not self.measurement_evidence:
            raise ValueError("A metric length requires measurement evidence")
        if self.status == "reviewed" and (self.length_m is None or self.access == "unknown"):
            raise ValueError("Reviewed annotations need documented length and access")
        return self
