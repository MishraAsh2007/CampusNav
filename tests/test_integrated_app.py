from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app as data_app
from backend.main import check_mongo_prerequisites
from campus_routing.api import create_app
from scripts.post_scraped_data import building_uploads

ROOT = Path(__file__).resolve().parents[1]


def test_mounted_service_uses_one_catalog_and_active_feed(monkeypatch):
    monkeypatch.setenv("CAMPUSNAV_MEMORY", "1")
    monkeypatch.setenv("CAMPUSNAV_ADMIN_KEY", "test-key")
    monkeypatch.delenv("CAMPUSNAV_DEMO", raising=False)
    with TestClient(create_app(data_app=data_app)) as client:
        assert client.get("/health").json()["storage_mode"] == "memory"
        assert client.get("/api/data/health").status_code == 200
        assert client.get("/closures/status").json()["status"] == "unavailable"
        building = next(b for b in building_uploads(ROOT / "data/buildings.json") if b.id == "ilc")
        payload = building.model_dump(mode="json")
        endpoint = "/api/data/buildings"
        assert client.post(endpoint, json=payload).status_code == 403
        client.headers["X-Admin-Key"] = "test-key"
        assert client.post(endpoint, json=payload).status_code == 201
        assert client.post(endpoint, json=payload).status_code == 409
        assert client.get(endpoint).json()[0]["entrances"][0]["id"] == building.entrances[0].id
        assert next(row for row in client.get("/buildings").json() if row["id"] == "ilc")["database_details"]

        now = datetime.now(UTC)
        report = {
            "lat": 42.3908, "lng": -72.5257, "type": "path", "status": "blocked",
            "timestamp": now.isoformat(), "title": "Path blocked",
        }
        response = client.post("/reports", json=report)
        assert response.status_code == 201, response.text
        report_id = response.json()["id"]
        assert [c["id"] for c in client.get("/closures").json()] == [report_id]
        assert client.get("/api/data/community-reports").json()[0]["id"] == report_id
        assert client.post(f"/reports/{report_id}/confirm").status_code == 200
        assert client.delete(f"/api/data/community-reports/{report_id}").status_code == 204
        assert client.get("/closures").json() == []


def test_guided_trip_checks_current_closures_at_the_selected_portal(monkeypatch):
    monkeypatch.setenv("CAMPUSNAV_MEMORY", "1")
    monkeypatch.setenv("CAMPUSNAV_ADMIN_KEY", "test-key")
    monkeypatch.delenv("CAMPUSNAV_DEMO", raising=False)
    with TestClient(create_app(data_app=data_app), headers={"X-Admin-Key": "test-key"}) as client:
        destination = {"building_id": "ilc", "node_id": "ilc-source-n151-f2"}
        plan = client.post("/navigation/plan", json={
            "origin": {"building_id": "campus-center"}, "destination": destination, "max_grade": 8,
        }).json()
        assert plan["status"] == "route_ready", plan
        assert plan["arrival_confirmation_required"]
        portal = plan["arrival_context"]
        req = {**portal, "confirmed": True, "continue_indoors": True,
               "destination": destination, "max_grade": 8}
        indoor = client.post("/navigation/arrive", json=req).json()
        assert indoor["status"] == "route_ready", indoor

        def lifts(result):
            return [step["asset_id"] for leg in result["journey"]["legs"] if leg["kind"] == "indoor"
                    for step in leg["transitions"] if step["kind"] == "elevator"]

        used = lifts(indoor)
        assert len(used) == 1
        now = datetime.now(UTC)

        def notice(asset_id, start, id_suffix):
            return {
                "id": f"test-{id_suffix}", "source_id": "test-maintenance", "source": "official",
                "notice_id": str(id_suffix), "location_id": asset_id, "asset_id": asset_id,
                "building_id": "ilc", "source_ref": "https://example.org/notice", "parser": "rules",
                "lat": 42.39, "lng": -72.52, "radius": 4, "type": "elevator", "status": "closed",
                "start_time": start.isoformat(), "end_time": (start + timedelta(hours=2)).isoformat(),
                "last_confirmed": now.isoformat(),
            }

        other = next(lift for lift in ("ilc-elevator-east", "ilc-elevator-west") if lift not in used)
        upload = {"kind": "official", "source_id": "test-maintenance", "observed_at": now.isoformat(),
                  "records": [notice(used[0], now - timedelta(minutes=1), 1),
                              notice(other, now + timedelta(hours=1), 2)]}
        posted = client.post("/api/data/scraper-imports", json=upload)
        assert posted.json() == {"applied": True, "collection": "OfficialClosures"}
        assert client.post("/api/data/scraper-imports", json=upload).json()["applied"] is False
        assert [row["id"] for row in client.get("/closures").json()] == ["test-1"]
        assert any(row["scheduled"] for row in client.get("/notices").json())
        rerouted = client.post("/navigation/arrive", json=req | {"closures": []}).json()
        assert rerouted["status"] == "route_ready", rerouted
        assert lifts(rerouted) == [other]

        upload["observed_at"] = (now + timedelta(seconds=1)).isoformat()
        upload["records"][1] = notice(other, now - timedelta(minutes=1), 2)
        assert client.post("/api/data/scraper-imports", json=upload).json()["applied"]
        assert client.post("/navigation/arrive", json=req).json()["status"] == "no_route"


def test_mongo_startup_check_only_reads_existing_metadata():
    class Inventory:
        def __init__(self):
            self.ttl = {"key": {"end_time": 1}, "expireAfterSeconds": 0}

        def list_collections(self, *, filter):
            yield {"name": filter["name"], "options": {"validationAction": "error"}}

        def __getitem__(self, name):
            indexes = [self.ttl] if name == "CommunityReports" else []
            return SimpleNamespace(list_indexes=lambda: iter(indexes))

    db = Inventory()
    before = check_mongo_prerequisites(db)
    assert check_mongo_prerequisites(db) == before
    db.ttl = {"key": {"end_time": 1}}
    with pytest.raises(RuntimeError, match="TTL index"):
        check_mongo_prerequisites(db)
