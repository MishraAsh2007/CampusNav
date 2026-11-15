"""Read the Data API's existing records as CampusNav routing and display data."""

from copy import deepcopy
from datetime import timedelta

from fastapi import HTTPException
from pydantic import ValidationError

from backend.main import ReportCreate, active_feed, list_all_official, save_report, utc_now

from .models import Closure


class DataBridge:
    def __init__(self, app):
        self.app = app

    def official_status(self, now=None):
        now = now or utc_now()
        captures = self.app.state.scraper_imports.list("official")
        sources = {
            item.source_id: {"mode": "published", "observed_at": item.observed_at, "message": ""}
            for item in captures
        }
        for record in self.app.state.closures.list_official():
            timestamp = record.snapshot_observed_at
            source_id = record.source_id or "official-reports"
            known = sources.get(source_id)
            if timestamp and (known is None or timestamp > known["observed_at"]):
                sources[source_id] = {
                    "mode": "cache" if record.snapshot_fallback else "published",
                    "observed_at": timestamp, "message": "",
                }
        observed = max((item["observed_at"] for item in sources.values()), default=None)
        stale = observed is None or any(
            row["mode"] == "cache" or now - row["observed_at"] > timedelta(hours=24)
            for row in sources.values()
        )
        return {
            "status": "unavailable" if not sources else "stale" if stale else "ready",
            "stale": stale,
            "generated_at": observed,
            "source_status": sources,
            "community_storage": self.app.state.storage_mode,
        }

    @staticmethod
    def display_closure(record):
        row = record.model_dump(mode="json")
        row["source"] = "community" if record.source in ("app", "demo") else record.source
        row["connector_id"] = record.asset_id
        row["title"] = record.title or f"{record.type.title()} interruption"
        return row

    def active(self, *, routing=False):
        rows = [self.display_closure(row) for row in active_feed(self.app, utc_now())]
        if not routing:
            return rows
        try:
            return [Closure.model_validate(
                row | {"type": "path" if row["type"] == "construction" else row["type"]}
            ) for row in rows]
        except ValidationError:
            raise HTTPException(
                503, "A stored closure does not fit the routing contract."
            ) from None

    def official(self, *, scheduled=False):
        now = utc_now()
        return [
            self.display_closure(row) | {"scheduled": row.start_time > now}
            for row in list_all_official(self.app)
            if (row.end_time is None or row.end_time > now) and (scheduled or row.start_time <= now)
        ]

    def public_reports(self):
        now = utc_now()
        captures = self.app.state.scraper_imports.list("public")
        rows = [row for capture in captures for row in capture.records if row.expires_at > now]
        sources = {item.source_id: {
            "state": "cached",
            "last_success_at": item.observed_at,
            "message": "Last published scrape",
        } for item in captures}
        return rows, {"status": "ready" if captures else "unavailable", "sources": sources,
                      "stale": not captures or any(now - item.observed_at > timedelta(hours=24)
                                                     for item in captures)}

    def submit(self, report):
        now = utc_now()
        if not now - timedelta(hours=24) <= report.timestamp <= now + timedelta(minutes=5):
            raise HTTPException(422, "Report must be from the last 24 hours and not in the future.")
        if report.status == "working":
            raise HTTPException(422, "Resolve a specific community report by ID.")
        if report.status == "under_repair":
            raise HTTPException(422, "Community storage accepts blocked or broken reports.")
        stored = save_report(self.app, ReportCreate(
            lat=report.lat, lng=report.lng, type=report.type,
            radius=4 if report.type == "elevator" else 8,
            title=report.title, description=report.description or None,
            building_id=report.building_id, floor_id=report.floor_id,
            asset_id=report.asset_id or report.connector_id,
        ))
        return self.display_closure(stored)

    def catalog(self, local):
        catalog = deepcopy(local)
        by_id = {row["id"]: row for row in catalog["buildings"]}
        for building in self.app.state.closures.list_buildings():
            view = building.model_dump(mode="json")
            row = by_id.get(building.id)
            if row is None:
                row = {
                    "id": building.id, "name": building.name, "code": building.id.upper(),
                    "category": "academic", "location": {"lat": building.lat, "lng": building.lng},
                    "in_routing_area": False, "entrances": [], "step_free_entrances": [],
                    "elevators": {"list": [], "total_count": None, "status": "unknown",
                                  "working_count": None, "floors_served": "Unknown"},
                    "door_type": "unknown", "accessible_restrooms": None,
                    "all_floors_accessible": False,
                }
                catalog["buildings"].append(row)
            row["name"] = building.name
            row["database_details"] = {
                "bathrooms": view["bathrooms"], "elevators": view["elevators"]
            }
            if building.elevator_count is not None:
                row["elevators"]["total_count"] = building.elevator_count
            lifts = {lift.asset_id: lift for lift in building.elevators if lift.asset_id}
            for lift in row["elevators"]["list"]:
                stored = lifts.get(lift.get("asset_id") or lift["id"])
                if stored:
                    lift["name"] = stored.location
            entrances = {entry.id: entry for entry in building.entrances if entry.id}
            for entry in row["entrances"]:
                if stored := entrances.get(entry["id"]):
                    entry["name"] = stored.name
                    if stored.IsKeyCardRequired is True:
                        entry["keycard_required"] = True
                    if stored.step_free is False:
                        entry["step_free"] = False
            row["step_free_entrances"] = [
                entry for entry in row["entrances"]
                if entry["step_free"] is True and not entry.get("keycard_required")
            ]
        return catalog
