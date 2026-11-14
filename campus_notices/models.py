from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from campus_routing.models import Closure, ContractModel, Coordinate

ClosureType = Literal["elevator", "ramp", "path"]


class Notice(ContractModel):
    id: str
    source_id: str
    source_ref: str
    building: str = ""
    text: str = Field(max_length=60000)
    categories: str = ""
    observed_at: AwareDatetime
    source_authority: Literal["official", "community", "publisher"] = "official"
    published_at: AwareDatetime | None = None
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    issues: list[str] = Field(default_factory=list)


class Location(Coordinate):
    id: str
    name: str
    type: ClosureType
    radius: float = Field(gt=0, le=1000)
    building_aliases: list[str] = Field(min_length=1)
    asset_phrases: list[str] = Field(min_length=1)
    reviewed: bool = False
    synthetic: bool = False
    evidence: str = Field(min_length=1)
    asset_id: str | None = None
    building_id: str | None = None
    floor_id: str | None = None


class Impact(ContractModel):
    type: ClosureType
    status: Literal["closed", "degraded", "working"]
    location_id: str | None = None
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    open_ended: bool = False
    evidence: str = Field(min_length=1, max_length=1500)
    needs_review: bool = False


class Extraction(ContractModel):
    relevant: bool
    impacts: list[Impact] = Field(default_factory=list, max_length=20)
    reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def consistent(self):
        if not self.relevant and self.impacts:
            raise ValueError("An irrelevant notice cannot contain impacts")
        return self


class PublishedClosure(Closure):
    id: str
    notice_id: str
    location_id: str
    source_id: str
    source_ref: str
    parser: Literal["rules", "gemini"]
    confirmation_kind: Literal["source_observed"] = "source_observed"


class ExternalReport(ContractModel):
    id: str
    source_id: str
    source_name: str
    source: Literal["official", "community", "publisher"]
    url: str
    title: str
    text: str
    published_at: AwareDatetime | None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    expires_at: AwareDatetime
    topics: list[str]
    location_candidates: list[str]
    parser: Literal["rules", "gemini", "unresolved"]
    extraction: Extraction | None
    review_reasons: list[str]
    review_status: Literal["needs_review"] = "needs_review"
    routing_eligible: Literal[False] = False


class SourceState(ContractModel):
    mode: Literal["live", "cache", "spreadsheet_fallback", "file"]
    observed_at: AwareDatetime
    attempted_at: AwareDatetime
    message: str = ""


class SourceBatch(ContractModel):
    source_id: str
    notices: list[Notice]
    state: SourceState


class Snapshot(ContractModel):
    version: Literal[1] = 1
    generated_at: AwareDatetime
    synthetic: bool = False
    closures: list[PublishedClosure]
    counts: dict[str, int]
    sources: list[str]
    source_observed_at: dict[str, AwareDatetime]
    source_status: dict[str, SourceState] = Field(default_factory=dict)
