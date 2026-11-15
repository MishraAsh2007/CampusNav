"""Store the latest successful processed snapshot for each scraper source."""

from threading import Lock
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AwareDatetime, Field, model_validator

from campus_notices.models import ExternalReport, PublishedClosure
from campus_routing.models import ContractModel


class SourceSnapshot(ContractModel):
    source_id: str = Field(min_length=1, max_length=150)
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_records(self):
        if any(record.source_id != self.source_id for record in self.records):
            raise ValueError("All records must belong to the snapshot source")
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError("Record IDs must be unique within the snapshot")
        return self

    @property
    def storage_id(self):
        return f"{self.kind}:{self.source_id}"

    @property
    def collection_name(self):
        return "OfficialClosures" if self.kind == "official" else "CommunityReports"


class OfficialSourceSnapshot(SourceSnapshot):
    kind: Literal["official"] = "official"
    records: list[PublishedClosure]

    @model_validator(mode="after")
    def validate_authority(self):
        if any(record.source != "official" for record in self.records):
            raise ValueError("Only official closures belong in an official snapshot")
        return self


class PublicSourceSnapshot(SourceSnapshot):
    kind: Literal["public"] = "public"
    records: list[ExternalReport]


ScraperSnapshot = Annotated[
    OfficialSourceSnapshot | PublicSourceSnapshot, Field(discriminator="kind")
]


class MemoryScraperImports:
    def __init__(self):
        self.snapshots: dict[str, ScraperSnapshot] = {}
        self.lock = Lock()

    def save(self, snapshot: ScraperSnapshot) -> bool:
        with self.lock:
            current = self.snapshots.get(snapshot.storage_id)
            if current and snapshot.observed_at <= current.observed_at:
                return False
            self.snapshots[snapshot.storage_id] = snapshot
            return True

    def list(self, kind) -> list[ScraperSnapshot]:
        with self.lock:
            return [row for _, row in sorted(self.snapshots.items()) if row.kind == kind]


class MongoScraperImports:
    def __init__(self, official, community):
        self.collections = {"official": official, "public": community}

    def save(self, snapshot: ScraperSnapshot) -> bool:
        from pymongo.errors import DuplicateKeyError, PyMongoError

        query = {"_id": snapshot.storage_id, "observed_at": {"$lt": snapshot.observed_at}}
        update = {"$set": snapshot.model_dump()}
        collection = self.collections[snapshot.kind]
        try:
            try:
                result = collection.update_one(query, update, upsert=True)
            except DuplicateKeyError:
                # A newer snapshot may already exist, or another upload just created the document.
                result = collection.update_one(query, update)
            return result.matched_count > 0 or result.upserted_id is not None
        except PyMongoError as exc:
            if getattr(exc, "code", None) == 121:
                raise HTTPException(409, "Database rejected the scraper document schema") from exc
            raise HTTPException(503, "Scraper import storage is unavailable") from exc

    def list(self, kind) -> list[ScraperSnapshot]:
        from pymongo.errors import PyMongoError

        try:
            rows = self.collections[kind].find({"kind": kind}, {"_id": 0}).sort("source_id", 1)
            model = OfficialSourceSnapshot if kind == "official" else PublicSourceSnapshot
            return [model.model_validate(row) for row in rows]
        except PyMongoError as exc:
            raise HTTPException(503, "Scraper import storage is unavailable") from exc
