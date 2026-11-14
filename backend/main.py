import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pymongo.collection import Collection


REPORT_LIFETIME = timedelta(hours=48)
REPORT_LIFETIME_MS = int(REPORT_LIFETIME.total_seconds() * 1000)
CLOSURES_FILE = Path(__file__).with_name("closures.json")
OFFICIAL_SNAPSHOT_ID = "umass-service-interruptions"


class ClosureLocation(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
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


def utc_now() -> datetime:
    now = datetime.now(UTC)
    # BSON dates have millisecond precision.
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


class MemoryClosures:
    def __init__(self) -> None:
        self.closures: list[Closure] = []
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


class MongoClosures:
    def __init__(self, collection: "Collection", official_snapshots: "Collection") -> None:
        self.collection = collection
        self.official_snapshots = official_snapshots

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
            closures = [
                Closure.model_validate({**document, "id": document["_id"]})
                for document in documents
            ]
            snapshot = self.official_snapshots.find_one({"_id": OFFICIAL_SNAPSHOT_ID})
            if snapshot:
                closures.extend(
                    closure for item in snapshot["closures"]
                    if (closure := Closure.model_validate(item)).start_time <= now
                )
            return closures
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

        with MongoClient(mongo_uri, tz_aware=True, timeoutMS=5000) as client:
            db = client[os.environ.get("MONGODB_DB", "campusnav")]
            collection = db["closures"]
            # TTL cleanup runs periodically. The read query also filters by end_time.
            new_expiry = {"$add": ["$last_confirmed", REPORT_LIFETIME_MS]}
            collection.update_many(
                {"source": "community", "end_time": {"$gt": utc_now()}, "$expr": {"$ne": ["$end_time", new_expiry]}},
                [{"$set": {"end_time": new_expiry}}],
            )
            collection.create_index("end_time", expireAfterSeconds=0)
            app.state.closures = MongoClosures(collection, db["official_snapshots"])
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
    CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"]
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/closures")
def get_closures(request: Request) -> list[Closure]:
    """Return currently active closures, most recently confirmed first."""
    closures = request.app.state.closures.active(utc_now())
    return sorted(closures, key=lambda closure: (closure.last_confirmed, closure.id), reverse=True)


@app.post("/reports", status_code=status.HTTP_201_CREATED)
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


@app.post("/reports/{report_id}/confirm")
def confirm_report(report_id: str, request: Request) -> Closure:
    """Keep an active community report for another 48 hours."""
    closure = request.app.state.closures.confirm(report_id)
    if closure is None:
        raise HTTPException(status_code=404, detail="Active community report not found")
    return closure
