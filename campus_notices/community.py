"""Local development report persistence. Role 4 can replace this store with Atlas."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from campus_routing.models import Coordinate

from .cache import atomic_json

LOCK = RLock()


class UserReport(Coordinate):
    type: Literal["elevator", "ramp", "path"]
    status: Literal["broken", "working", "blocked", "under_repair"]
    timestamp: AwareDatetime
    title: str = Field(default="Community report", max_length=200)
    description: str = Field(default="", max_length=2000)
    building_id: str | None = None
    connector_id: str | None = None
    asset_id: str | None = None
    floor_id: str | None = None

    @model_validator(mode="after")
    def scope(self):
        if (self.floor_id or self.asset_id) and not self.building_id:
            raise ValueError("Indoor report scope requires building_id")
        return self


class ReportStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Report store is invalid")
        return data

    def active(self, now=None):
        now = now or datetime.now(UTC)
        with LOCK:
            return [c for c in self.read() if datetime.fromisoformat(c["end_time"]) > now]

    def submit(self, report, now=None):
        now = now or datetime.now(UTC)
        if now - report.timestamp > timedelta(hours=24) or report.timestamp - now > timedelta(
            minutes=5
        ):
            raise ValueError("Report must be from the last 24 hours and not in the future")
        with LOCK:
            current = self.active(now)
            from math import cos, hypot, radians

            def matches(c):
                if c["type"] != report.type:
                    return False
                if c.get("floor_id") != report.floor_id:
                    return False
                if c.get("asset_id") or report.asset_id:
                    return (
                        c.get("asset_id") == report.asset_id
                        and c.get("building_id") == report.building_id
                    )
                if c.get("connector_id") or report.connector_id:
                    return c.get("connector_id") == report.connector_id
                return (
                    hypot(
                        (c["lat"] - report.lat) * 111320,
                        (c["lng"] - report.lng) * 111320 * cos(radians(report.lat)),
                    )
                    < 6
                )

            current = [c for c in current if not matches(c)]
            closure = {
                "id": "community-" + uuid4().hex,
                "lat": report.lat,
                "lng": report.lng,
                "radius": 4 if report.type == "elevator" else 8,
                "type": report.type,
                "status": "repaired"
                if report.status == "working"
                else "degraded"
                if report.status == "under_repair"
                else "closed",
                "source": "community",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=24)).isoformat(),
                "last_confirmed": now.isoformat(),
                "title": report.title,
                "description": report.description,
                "building_id": report.building_id,
                "connector_id": report.connector_id,
                "asset_id": report.asset_id,
                "floor_id": report.floor_id,
                "confirmations_count": 1,
            }
            if report.status != "working":
                current.append(closure)
            atomic_json(self.path, current)
            return closure

    def confirm(self, ident, now=None):
        now = now or datetime.now(UTC)
        with LOCK:
            current = self.active(now)
            closure = next((c for c in current if c["id"] == ident), None)
            if closure is None:
                raise KeyError(ident)
            closure.update(
                last_confirmed=now.isoformat(),
                end_time=(now + timedelta(hours=24)).isoformat(),
                confirmations_count=closure["confirmations_count"] + 1,
            )
            atomic_json(self.path, current)
            return closure
