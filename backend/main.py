import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

from campus_notices.models import ExternalReport

from .scraper_imports import MemoryScraperImports, MongoScraperImports, ScraperSnapshot

if TYPE_CHECKING:
    from pymongo.collection import Collection


REPORT_LIFETIME = timedelta(hours=48)
REPORT_LIFETIME_MS = int(REPORT_LIFETIME.total_seconds() * 1000)
CLOSURES_FILE = Path(__file__).with_name("closures.json")
OFFICIAL_SNAPSHOT_ID = "umass-service-interruptions"
BUILDING_ID = Annotated[str, Field(pattern=r"^[a-z0-9]+([-_][a-z0-9]+)*$")]
REFERENCE_ID = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
COMMUNITY_SOURCES = ("community", "app")


class MapPoint(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]


class Entrance(MapPoint):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: REFERENCE_ID | None = None
    name: Annotated[str, Field(min_length=1)]
    step_free: bool | None
    hasAutoDoorOpener: bool | None = None
    isAccessibleToAllFloors: bool | None = None
    IsKeyCardRequired: bool | None = None
    automatic_door: bool | None = None

    @model_validator(mode="after")
    def normalize_door_opener(self) -> "Entrance":
        if self.hasAutoDoorOpener is None:
            self.hasAutoDoorOpener = self.automatic_door
        elif self.automatic_door is not None and self.hasAutoDoorOpener != self.automatic_door:
            raise ValueError("Door opener fields disagree")
        self.automatic_door = self.hasAutoDoorOpener
        return self


class IndoorReferences(BaseModel):
    building_id: REFERENCE_ID | None = None
    asset_id: REFERENCE_ID | None = None
    floor_id: REFERENCE_ID | None = None

    @model_validator(mode="after")
    def floor_requires_building(self):
        if self.floor_id is not None and self.building_id is None:
            raise ValueError("building_id is required when floor_id is set")
        return self


class IndoorLocation(IndoorReferences):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location: Annotated[str, Field(min_length=1)]
    lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    lng: Annotated[float, Field(ge=-180, le=180)] | None = None


class Bathroom(IndoorLocation):
    transfer_type: Annotated[str, Field(min_length=1)] | None


class Building(MapPoint):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: BUILDING_ID
    name: Annotated[str, Field(min_length=1)]
    entrances: list[Entrance]
    elevator_count: Annotated[int, Field(ge=0)] | None = None
    elevators: list[IndoorLocation] = Field(default_factory=list)
    bathrooms: list[Bathroom] = Field(default_factory=list)

    @model_validator(mode="after")
    def set_elevator_count(self) -> "Building":
        if self.elevator_count is None and "elevator_count" not in self.model_fields_set:
            self.elevator_count = len(self.elevators)
        elif self.elevator_count is not None and self.elevator_count < len(self.elevators):
            raise ValueError("Elevator count cannot be smaller than the list of elevator locations")
        return self


class EntranceWrite(Entrance):
    id: REFERENCE_ID


class ElevatorWrite(IndoorLocation):
    asset_id: REFERENCE_ID


class BuildingWrite(Building):
    entrances: list[EntranceWrite]
    elevators: list[ElevatorWrite] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self):
        if len({entry.id for entry in self.entrances}) != len(self.entrances):
            raise ValueError("Entrance IDs must be unique within a building")
        if len({lift.asset_id for lift in self.elevators}) != len(self.elevators):
            raise ValueError("Elevator asset IDs must be unique within a building")
        if any(unit.building_id not in (None, self.id) for unit in self.elevators + self.bathrooms):
            raise ValueError("Indoor location building_id must match the building ID")
        return self


class ClosureLocation(MapPoint, IndoorReferences):
    radius: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 10.0
    type: Literal["elevator", "ramp", "path", "construction"]


class ReportCreate(ClosureLocation):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    description: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    source: Literal["community", "app"] = "community"


class SnapshotObservation(BaseModel):
    snapshot_observed_at: AwareDatetime | None = None
    snapshot_fallback: bool | None = None


class NoticeProvenance(SnapshotObservation):
    source_ref: str | None = Field(default=None, exclude=True)
    source_id: str | None = None
    confirmation_kind: str | None = None
    published_at: AwareDatetime | None = None


class Closure(ClosureLocation, NoticeProvenance):
    id: str
    status: Literal["closed", "degraded"] = "closed"
    source: Literal["community", "app", "demo", "official"] = "community"
    start_time: AwareDatetime
    end_time: AwareDatetime | None
    last_confirmed: AwareDatetime | None
    ingested_at: AwareDatetime | None = None
    title: str | None = None
    details: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def fill_official_description(self) -> "Closure":
        if self.source == "official" and self.description is None:
            self.description = self.details or self.title
        return self

    @computed_field
    @property
    def last_updated(self) -> datetime | None:
        return self.last_confirmed

    @computed_field
    @property
    def location(self) -> MapPoint:
        return MapPoint(lat=self.lat, lng=self.lng)


class OfficialNotice(IndoorReferences, NoticeProvenance):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, Field(min_length=1)]
    status: Literal["closed", "degraded"] = "closed"
    type: Literal["elevator", "ramp", "path", "construction"]
    radius: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 10.0
    location: MapPoint | None = None
    lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    lng: Annotated[float, Field(ge=-180, le=180)] | None = None
    title: Annotated[str, Field(min_length=1)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    details: str | None = None
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    last_confirmed: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_notice(self) -> "OfficialNotice":
        if self.location is not None:
            if (
                (self.lat is not None and self.lat != self.location.lat)
                or (self.lng is not None and self.lng != self.location.lng)
            ):
                raise ValueError("Location disagrees with top-level coordinates")
            self.lat, self.lng = self.location.lat, self.location.lng
        if self.lat is None or self.lng is None:
            raise ValueError("Location coordinates are required")
        self.description = self.description or self.details or self.title
        if not self.description:
            raise ValueError("A description is required")
        self.title = self.title or self.description
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        return self


class OfficialSnapshot(SnapshotObservation):
    model_config = ConfigDict(extra="forbid")

    closures: list[OfficialNotice]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "OfficialSnapshot":
        if len({notice.id for notice in self.closures}) != len(self.closures):
            raise ValueError("Official closure IDs must be unique")
        return self


def utc_now() -> datetime:
    now = datetime.now(UTC)
    # BSON dates have millisecond precision.
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


class MemoryClosures:
    def __init__(self) -> None:
        self.closures: list[Closure] = []
        self.official_closures: list[Closure] = []
        self.buildings: dict[str, Building] = {}
        self.lock = Lock()

    def add(self, closure: Closure) -> None:
        with self.lock:
            self.closures.append(closure)

    def active(self, now: datetime) -> list[Closure]:
        with self.lock:
            self.closures = [
                closure for closure in self.closures
                if closure.end_time is None or now < closure.end_time
            ]
            return [closure for closure in self.closures if closure.start_time <= now]

    def confirm(self, report_id: str) -> Closure | None:
        with self.lock:
            now = utc_now()
            for index, closure in enumerate(self.closures):
                if (
                    closure.id == report_id and closure.source in COMMUNITY_SOURCES
                    and closure.end_time is not None and closure.end_time > now
                ):
                    confirmed_at = max(now, closure.last_confirmed or now)
                    updated = closure.model_copy(update={
                        "last_confirmed": confirmed_at, "end_time": confirmed_at + REPORT_LIFETIME,
                    })
                    self.closures[index] = updated
                    return updated
        return None

    def delete_report(self, report_id: str) -> bool:
        with self.lock:
            remaining = [c for c in self.closures if c.id != report_id or c.source not in COMMUNITY_SOURCES]
            deleted = len(remaining) != len(self.closures)
            self.closures = remaining
            return deleted

    def list_official(self) -> list[Closure]:
        with self.lock:
            return list(self.official_closures)

    def replace_official(self, closures: list[Closure]) -> None:
        with self.lock:
            self.official_closures = closures

    def list_buildings(self) -> list[Building]:
        with self.lock:
            return list(self.buildings.values())

    def add_building(self, building: Building, *, replace: bool = False) -> None:
        with self.lock:
            if not replace and building.id in self.buildings:
                raise HTTPException(status_code=409, detail="Building ID already exists")
            self.buildings[building.id] = building


class MongoClosures:
    def __init__(
        self, collection: "Collection", official_snapshots: "Collection", buildings: "Collection"
    ) -> None:
        self.collection = collection
        self.official_snapshots = official_snapshots
        self.buildings = buildings

    def add(self, closure: Closure) -> None:
        from pymongo.errors import PyMongoError

        document = closure.model_dump(exclude_unset=True)
        document["_id"] = document.pop("id")
        try:
            self.collection.insert_one(document)
        except PyMongoError as error:
            if getattr(error, "code", None) == 121:
                raise HTTPException(409, "Database rejected the community report document") from error
            raise HTTPException(status_code=503, detail="Closure storage is unavailable") from error

    def active(self, now: datetime) -> list[Closure]:
        from pymongo.errors import PyMongoError

        try:
            documents = self.collection.find(
                {"source": {"$in": COMMUNITY_SOURCES}, "start_time": {"$lte": now}, "end_time": {"$gt": now}}
            )
            return [
                Closure.model_validate({**document, "id": document["_id"]})
                for document in documents
            ]
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="Closure storage is unavailable") from error

    def confirm(self, report_id: str) -> Closure | None:
        from pymongo import ReturnDocument
        from pymongo.errors import PyMongoError

        try:
            document = self.collection.find_one_and_update(
                {
                    "_id": report_id, "source": {"$in": COMMUNITY_SOURCES},
                    "$expr": {"$gt": ["$end_time", "$$NOW"]},
                },
                [
                    {"$set": {"last_confirmed": {"$max": ["$$NOW", "$last_confirmed"]}}},
                    {"$set": {
                        "end_time": {"$add": ["$last_confirmed", REPORT_LIFETIME_MS]},
                        "last_updated": "$last_confirmed",
                    }},
                ],
                return_document=ReturnDocument.AFTER,
            )
            if document is not None:
                return Closure.model_validate({**document, "id": document["_id"]})
            return None
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="Closure storage is unavailable") from error

    def delete_report(self, report_id: str) -> bool:
        from pymongo.errors import PyMongoError

        try:
            return bool(self.collection.delete_one({
                "_id": report_id, "source": {"$in": COMMUNITY_SOURCES},
            }).deleted_count)
        except PyMongoError as error:
            raise HTTPException(503, "Closure storage is unavailable") from error

    def list_official(self) -> list[Closure]:
        from pymongo.errors import PyMongoError

        try:
            snapshot = self.official_snapshots.find_one({"_id": OFFICIAL_SNAPSHOT_ID})
            return [Closure.model_validate(item) for item in snapshot["closures"]] if snapshot else []
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="Official closure storage is unavailable") from error

    def replace_official(self, closures: list[Closure]) -> None:
        from pymongo.errors import PyMongoError

        try:
            self.official_snapshots.update_one(
                {"_id": OFFICIAL_SNAPSHOT_ID},
                {"$set": {"closures": [
                    closure.model_dump() | ({"source_ref": closure.source_ref} if closure.source_ref else {})
                    for closure in closures
                ]}},
                upsert=True,
            )
        except PyMongoError as error:
            if getattr(error, "code", None) == 121:
                raise HTTPException(409, "Database rejected the official report document") from error
            raise HTTPException(status_code=503, detail="Official closure storage is unavailable") from error

    def list_buildings(self) -> list[Building]:
        from pymongo.errors import PyMongoError

        try:
            buildings = []
            for document in self.buildings.find():
                document["id"] = document.pop("_id")
                buildings.append(Building.model_validate(document))
            return buildings
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="Building storage is unavailable") from error

    def add_building(self, building: Building, *, replace: bool = False) -> None:
        from pymongo.errors import DuplicateKeyError, PyMongoError

        document = building.model_dump()
        document["_id"] = document.pop("id")
        for unit in document["entrances"] + document["elevators"] + document["bathrooms"]:
            for key in ("id", "building_id", "asset_id", "floor_id"):
                if unit.get(key) is None:
                    unit.pop(key, None)
        try:
            if replace:
                self.buildings.replace_one({"_id": building.id}, document, upsert=True)
            else:
                self.buildings.insert_one(document)
        except DuplicateKeyError as error:
            raise HTTPException(status_code=409, detail="Building ID already exists") from error
        except PyMongoError as error:
            if getattr(error, "code", None) == 121:
                raise HTTPException(409, "Database rejected the building document schema") from error
            raise HTTPException(status_code=503, detail="Building storage is unavailable") from error


def seed_demo(store: MemoryClosures) -> None:
    now = datetime.now(UTC)
    for i, document in enumerate(json.loads(CLOSURES_FILE.read_text(encoding="utf-8"))):
        fixture = Closure.model_validate({"id": f"demo-{i + 1}", **document})
        store.add(
            fixture.model_copy(
                update={
                    "start_time": now,
                    "end_time": now + (fixture.end_time - fixture.start_time),
                    "last_confirmed": now,
                }
            )
        )


def check_mongo_prerequisites(db) -> dict:
    """Inventory existing collections without attempting to provision or update them."""
    inventory = {}
    for name in ("Buildings", "OfficialClosures", "CommunityReports"):
        info = next(db.list_collections(filter={"name": name}), None)
        if info is None:
            raise RuntimeError(f"MongoDB collection {name} is missing. Check MONGODB_DB.")
        inventory[name] = {"options": info.get("options", {}), "indexes": list(db[name].list_indexes())}
    if not any(
        list(index["key"].items()) == [("end_time", 1)] and index.get("expireAfterSeconds") == 0
        for index in inventory["CommunityReports"]["indexes"]
    ):
        raise RuntimeError("MongoDB CommunityReports is missing its existing end_time TTL index.")
    return inventory


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_uri = None if os.getenv("CAMPUSNAV_MEMORY") == "1" else os.getenv("MONGODB_URI")
    if mongo_uri:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError

        with MongoClient(mongo_uri, tz_aware=True, timeoutMS=5000) as client:
            db = client[os.environ.get("MONGODB_DB") or "campusnav"]
            try:
                app.state.mongo_inventory = check_mongo_prerequisites(db)
            except PyMongoError:
                raise RuntimeError("Could not read MongoDB metadata. Check connection and permissions.") from None
            collection = db["CommunityReports"]
            app.state.storage_mode = "mongo"
            app.state.closures = MongoClosures(collection, db["OfficialClosures"], db["Buildings"])
            app.state.scraper_imports = MongoScraperImports(db["OfficialClosures"], collection)
            yield
    else:
        store = MemoryClosures()
        if os.environ.get("CAMPUSNAV_DEMO") == "1":
            seed_demo(store)
        app.state.closures = store
        app.state.scraper_imports = MemoryScraperImports()
        app.state.storage_mode = "memory"
        yield


app = FastAPI(title="CampusNav Data API", lifespan=lifespan)
# Any origin by default, so the separately deployed Vercel frontend (and previews) can call this API.
# Set CORS_ORIGINS (comma-separated) to restrict it.
origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)
admin_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def require_admin(key: Annotated[str | None, Security(admin_header)]) -> None:
    expected = os.environ.get("CAMPUSNAV_ADMIN_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin writes are disabled")
    if key is None or not compare_digest(key.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid admin key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scraper-imports", dependencies=[Depends(require_admin)])
def import_scraper_snapshot(snapshot: ScraperSnapshot, request: Request) -> dict[str, bool | str]:
    if snapshot.observed_at > utc_now() + timedelta(minutes=5):
        raise HTTPException(422, "Source observation time is in the future")
    return {
        "applied": request.app.state.scraper_imports.save(snapshot),
        "collection": snapshot.collection_name,
    }


@app.get("/external-reports")
def get_external_reports(request: Request) -> list[ExternalReport]:
    now = utc_now()
    return [
        report
        for snapshot in request.app.state.scraper_imports.list("public")
        for report in snapshot.records
        if report.expires_at > now
    ]


def list_all_official(data_app: FastAPI) -> list[Closure]:
    saved = data_app.state.closures.list_official()
    by_id = {closure.id: closure for closure in saved}
    for snapshot in data_app.state.scraper_imports.list("official"):
        for record in snapshot.records:
            # The scraper's private source reference remains in the database record.
            description = f"UMass Facilities {record.type} interruption"
            by_id.setdefault(
                record.id,
                Closure.model_validate(record.model_dump() | {
                    "title": description,
                    "snapshot_observed_at": snapshot.observed_at,
                    "snapshot_fallback": False,
                }),
            )
    return list(by_id.values())


@app.get("/closures")
def get_closures(request: Request) -> list[Closure]:
    """Return currently active closures, most recently confirmed first."""
    return active_feed(request.app, utc_now())


def active_feed(data_app: FastAPI, now: datetime, *, official: list[Closure] | None = None) -> list[Closure]:
    store = data_app.state.closures
    closures = store.active(now)
    closures.extend(
        notice for notice in (list_all_official(data_app) if official is None else official)
        if notice.start_time <= now and (notice.end_time is None or now < notice.end_time)
    )
    return sorted(closures, key=closure_order, reverse=True)


def closure_order(closure: Closure):
    return closure.last_confirmed is not None, closure.last_confirmed, closure.id


@app.get("/buildings")
def get_buildings(request: Request) -> list[Building]:
    return sorted(request.app.state.closures.list_buildings(), key=lambda building: building.id)


@app.post("/buildings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_building(building: BuildingWrite, request: Request) -> Building:
    request.app.state.closures.add_building(building)
    return building


@app.put("/buildings/{building_id}", dependencies=[Depends(require_admin)])
def replace_building(building_id: BUILDING_ID, building: BuildingWrite, request: Request) -> Building:
    if building_id != building.id:
        raise HTTPException(422, "Building ID must match the URL")
    request.app.state.closures.add_building(building, replace=True)
    return building


@app.get("/official-reports")
def get_official_closures(request: Request) -> list[Closure]:
    """Return the current official snapshot, including any scheduled notices."""
    return list_all_official(request.app)


@app.post("/official-reports", dependencies=[Depends(require_admin)])
def replace_official_closures(snapshot: OfficialSnapshot, request: Request) -> list[Closure]:
    """Replace the complete current official snapshot."""
    now = utc_now()
    if any(
        notice.start_time is None and notice.end_time is not None and notice.end_time <= now
        for notice in snapshot.closures
    ):
        raise HTTPException(status_code=422, detail="An end time before posting requires an earlier start time")
    closures = [
        Closure(
            **notice.model_dump(exclude={"start_time", "location", "snapshot_observed_at", "snapshot_fallback"}),
            source="official",
            source_ref=notice.source_ref,
            start_time=notice.start_time or now,
            ingested_at=now,
            snapshot_observed_at=notice.snapshot_observed_at or snapshot.snapshot_observed_at,
            snapshot_fallback=(notice.snapshot_fallback if notice.snapshot_fallback is not None else snapshot.snapshot_fallback),
        )
        for notice in snapshot.closures
    ]
    request.app.state.closures.replace_official(closures)
    return closures


@app.get("/community-reports")
def get_reports(request: Request) -> list[Closure]:
    """Return active community reports."""
    reports = request.app.state.closures.active(utc_now())
    return sorted(
        (report for report in reports if report.source in COMMUNITY_SOURCES),
        key=closure_order,
        reverse=True,
    )


@app.post("/community-reports", status_code=status.HTTP_201_CREATED)
def create_report(report: ReportCreate, request: Request) -> Closure:
    """Record a community report and make its closure immediately available."""
    return save_report(request.app, report)


def save_report(data_app: FastAPI, report: ReportCreate) -> Closure:
    now = utc_now()
    closure = Closure(
        **report.model_dump(exclude_none=True),
        id=str(uuid4()),
        status="closed",
        start_time=now,
        end_time=now + REPORT_LIFETIME,
        last_confirmed=now,
    )
    data_app.state.closures.add(closure)
    return closure


@app.delete("/community-reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_community_report(report_id: str, request: Request) -> Response:
    if not request.app.state.closures.delete_report(report_id):
        raise HTTPException(404, "Community report not found")
    return Response(status_code=204)


@app.post("/community-reports/{report_id}/confirm")
def confirm_report(report_id: str, request: Request) -> Closure:
    """Keep an active community report for another 48 hours."""
    closure = request.app.state.closures.confirm(report_id)
    if closure is None:
        raise HTTPException(status_code=404, detail="Active community report not found")
    return closure
