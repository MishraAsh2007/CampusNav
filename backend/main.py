import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from pymongo.collection import Collection


REPORT_LIFETIME = timedelta(hours=48)
REPORT_LIFETIME_MS = int(REPORT_LIFETIME.total_seconds() * 1000)
CLOSURES_FILE = Path(__file__).with_name("closures.json")
OFFICIAL_SNAPSHOT_ID = "umass-service-interruptions"


class MapPoint(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]


class Entrance(MapPoint):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1)]
    step_free: bool
    automatic_door: bool


class Building(MapPoint):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
    name: Annotated[str, Field(min_length=1)]
    entrances: list[Entrance]
    elevator_count: Annotated[int, Field(ge=0)]


class ClosureLocation(MapPoint):
    radius: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 10.0
    type: Literal["elevator", "ramp", "path", "construction"]


class ReportCreate(ClosureLocation):
    model_config = ConfigDict(extra="forbid")


class Closure(ClosureLocation):
    id: str
    status: Literal["closed"] = "closed"
    source: Literal["community", "demo", "official"] = "community"
    start_time: AwareDatetime
    end_time: AwareDatetime | None
    last_confirmed: AwareDatetime
    title: str | None = None
    details: str | None = None


class OfficialNotice(ClosureLocation):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, Field(min_length=1)]
    title: Annotated[str, Field(min_length=1)]
    details: str | None = None
    start_time: AwareDatetime | None = None


class OfficialSnapshot(BaseModel):
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
                    closure.id == report_id and closure.source == "community"
                    and closure.end_time is not None and closure.end_time > now
                ):
                    confirmed_at = max(now, closure.last_confirmed)
                    updated = closure.model_copy(update={
                        "last_confirmed": confirmed_at, "end_time": confirmed_at + REPORT_LIFETIME,
                    })
                    self.closures[index] = updated
                    return updated
        return None

    def list_official(self) -> list[Closure]:
        with self.lock:
            return list(self.official_closures)

    def replace_official(self, closures: list[Closure]) -> None:
        with self.lock:
            self.official_closures = closures

    def list_buildings(self) -> list[Building]:
        with self.lock:
            return list(self.buildings.values())

    def add_building(self, building: Building) -> None:
        with self.lock:
            if building.id in self.buildings:
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

        document = closure.model_dump()
        document["_id"] = document.pop("id")
        try:
            self.collection.insert_one(document)
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="Closure storage is unavailable") from error

    def active(self, now: datetime) -> list[Closure]:
        from pymongo.errors import PyMongoError

        try:
            documents = self.collection.find(
                {"start_time": {"$lte": now}, "end_time": {"$gt": now}}
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
                    "_id": report_id, "source": "community",
                    "$expr": {"$gt": ["$end_time", "$$NOW"]},
                },
                [
                    {"$set": {"last_confirmed": {"$max": ["$$NOW", "$last_confirmed"]}}},
                    {"$set": {"end_time": {"$add": ["$last_confirmed", REPORT_LIFETIME_MS]}}},
                ],
                return_document=ReturnDocument.AFTER,
            )
            if document is not None:
                return Closure.model_validate({**document, "id": document["_id"]})
            return None
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="Closure storage is unavailable") from error

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
                {"$set": {"closures": [closure.model_dump() for closure in closures]}},
                upsert=True,
            )
        except PyMongoError as error:
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

    def add_building(self, building: Building) -> None:
        from pymongo.errors import DuplicateKeyError, PyMongoError

        document = building.model_dump()
        document["_id"] = document.pop("id")
        try:
            self.buildings.insert_one(document)
        except DuplicateKeyError as error:
            raise HTTPException(status_code=409, detail="Building ID already exists") from error
        except PyMongoError as error:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_uri = os.environ.get("MONGODB_URI")
    if mongo_uri:
        from pymongo import MongoClient
        from pymongo.errors import OperationFailure

        with MongoClient(mongo_uri, tz_aware=True, timeoutMS=5000) as client:
            db = client[os.environ.get("MONGODB_DB", "campusnav")]
            for name in ("Buildings", "OfficialClosures"):
                try:
                    db.create_collection(name, check_exists=False)
                except OperationFailure as error:
                    if error.code != 48:  # NamespaceExists
                        raise
            collection = db["CommunityReports"]
            # TTL cleanup runs periodically. The read query also filters by end_time.
            new_expiry = {"$add": ["$last_confirmed", REPORT_LIFETIME_MS]}
            collection.update_many(
                {"source": "community", "end_time": {"$gt": utc_now()}, "$expr": {"$ne": ["$end_time", new_expiry]}},
                [{"$set": {"end_time": new_expiry}}],
            )
            collection.create_index("end_time", expireAfterSeconds=0)
            app.state.closures = MongoClosures(collection, db["OfficialClosures"], db["Buildings"])
            yield
    else:
        store = MemoryClosures()
        if os.environ.get("CAMPUSNAV_DEMO") == "1":
            seed_demo(store)
        app.state.closures = store
        yield


app = FastAPI(title="CampusNav Data API", lifespan=lifespan)
origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
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


@app.get("/closures")
def get_closures(request: Request) -> list[Closure]:
    """Return currently active closures, most recently confirmed first."""
    now = utc_now()
    store = request.app.state.closures
    closures = store.active(now)
    closures.extend(notice for notice in store.list_official() if notice.start_time <= now)
    return sorted(closures, key=lambda closure: (closure.last_confirmed, closure.id), reverse=True)


@app.get("/buildings")
def get_buildings(request: Request) -> list[Building]:
    return sorted(request.app.state.closures.list_buildings(), key=lambda building: building.id)


@app.post("/buildings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_building(building: Building, request: Request) -> Building:
    request.app.state.closures.add_building(building)
    return building


@app.get("/official-reports")
def get_official_closures(request: Request) -> list[Closure]:
    """Return the current official snapshot, including any scheduled notices."""
    return request.app.state.closures.list_official()


@app.post("/official-reports", dependencies=[Depends(require_admin)])
def replace_official_closures(snapshot: OfficialSnapshot, request: Request) -> list[Closure]:
    """Replace the complete current official snapshot."""
    now = utc_now()
    closures = [
        Closure(
            **notice.model_dump(exclude={"start_time"}),
            source="official",
            start_time=notice.start_time or now,
            end_time=None,
            last_confirmed=now,
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
        (report for report in reports if report.source == "community"),
        key=lambda report: (report.last_confirmed, report.id),
        reverse=True,
    )


@app.post("/community-reports", status_code=status.HTTP_201_CREATED)
def create_report(report: ReportCreate, request: Request) -> Closure:
    """Record a community report and make its closure immediately available."""
    now = utc_now()
    closure = Closure(
        **report.model_dump(),
        id=str(uuid4()),
        start_time=now,
        end_time=now + REPORT_LIFETIME,
        last_confirmed=now,
    )
    request.app.state.closures.add(closure)
    return closure


@app.post("/community-reports/{report_id}/confirm")
def confirm_report(report_id: str, request: Request) -> Closure:
    """Keep an active community report for another 48 hours."""
    closure = request.app.state.closures.confirm(report_id)
    if closure is None:
        raise HTTPException(status_code=404, detail="Active community report not found")
    return closure
