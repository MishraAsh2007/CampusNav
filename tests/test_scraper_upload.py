from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from backend.main import app
from scripts.post_scraped_data import ROOT, building_uploads


def test_snapshot_retry_and_empty_refresh_preserve_other_source(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("CAMPUSNAV_DEMO", raising=False)
    monkeypatch.setenv("CAMPUSNAV_ADMIN_KEY", "test-key")
    now = datetime.now(UTC) - timedelta(minutes=1)
    public = {
        "kind": "public",
        "source_id": "umass-reddit",
        "observed_at": now.isoformat(),
        "records": [
            {
                "id": "public-1",
                "source_id": "umass-reddit",
                "source_name": "r/umass",
                "source": "community",
                "url": "https://www.reddit.com/r/umass/",
                "title": "Elevator trouble",
                "text": "The elevator may be out.",
                "published_at": now.isoformat(),
                "first_seen_at": now.isoformat(),
                "last_seen_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "topics": ["elevator"],
                "location_candidates": [],
                "parser": "unresolved",
                "extraction": None,
                "review_reasons": ["Needs verification"],
            }
        ],
    }
    official = {
        "kind": "official",
        "source_id": "umass-maintenance",
        "observed_at": now.isoformat(),
        "records": [
            {
                "id": "stable-id",
                "notice_id": "notice-1",
                "location_id": "loc-1",
                "source_id": "umass-maintenance",
                "source_ref": "https://example.org/notice-1",
                "parser": "rules",
                "lat": 42.39,
                "lng": -72.53,
                "radius": 12,
                "type": "elevator",
                "source": "official",
                "status": "degraded",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),
                "last_confirmed": now.isoformat(),
            }
        ],
    }
    endpoint = "/scraper-imports"
    with TestClient(app) as client:
        assert client.post(endpoint, json=official).status_code == 403
        client.headers["X-Admin-Key"] = "test-key"
        manual = {"id": "manual", "type": "path", "title": "Path closed", "lat": 42, "lng": -72}
        assert client.post("/official-reports", json={"closures": [manual]}).status_code == 200
        assert client.post(endpoint, json=official | {"source_id": "other"}).status_code == 422
        assert client.post(endpoint, json=official).json() == {
            "applied": True,
            "collection": "OfficialClosures",
        }
        assert client.post(endpoint, json=public).json() == {
            "applied": True,
            "collection": "CommunityReports",
        }
        active = {row["id"]: row for row in client.get("/closures").json()}
        assert set(active) == {"manual", "stable-id"}
        assert active["stable-id"]["status"] == "degraded"
        assert "source_ref" not in active["stable-id"]
        assert client.get("/community-reports").json() == []
        review = client.get("/external-reports").json()
        assert review[0]["id"] == "public-1" and review[0]["routing_eligible"] is False

        cleared = official | {
            "records": [],
            "observed_at": (now + timedelta(seconds=1)).isoformat(),
        }
        assert client.post(endpoint, json=cleared).json()["applied"] is True
        assert client.post(endpoint, json=official).json()["applied"] is False
        assert client.post(endpoint, json=cleared).json()["applied"] is False
        assert [row["id"] for row in client.get("/official-reports").json()] == ["manual"]
        assert client.get("/external-reports").json() == review


def test_catalog_import_preserves_unknown_access_and_existing_buildings(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("CAMPUSNAV_DEMO", raising=False)
    monkeypatch.setenv("CAMPUSNAV_ADMIN_KEY", "test-key")
    buildings = building_uploads(ROOT / "data/buildings.json")
    building = next(row for row in buildings if row.id == "ilc")
    assert building.elevator_count is None and building.elevators
    payload = building.model_dump(mode="json")
    assert payload["entrances"][0]["step_free"] is None
    with TestClient(app, headers={"X-Admin-Key": "test-key"}) as client:
        assert client.post("/buildings", json=payload).status_code == 201
        changed = payload | {"name": "New name"}
        assert client.post("/buildings", json=changed).status_code == 409
        assert client.get("/buildings").json() == [payload]
