import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campus_routing.api import create_app
from campus_routing.engine import RoutingError
from campus_routing.indoor import IndoorEngine, IndoorRouteRequest, read_indoor

ROOT = Path(__file__).resolve().parents[1]


def test_library_source_destination_route_is_available():
    data = read_indoor(ROOT / "data/indoor/library.json")
    result = IndoorEngine(data).route(
        IndoorRouteRequest(
            building_id="library",
            start_node_id="lib-lobby-2nd-floor",
            end_node_id="lib-source-2f9cf0cb673d6873f4c3",
        )
    )
    assert result["node_path"][-1] == "lib-source-2f9cf0cb673d6873f4c3"
    assert any("pilot waypoint" in warning for warning in result["warnings"])


def test_ilc_field_conflicts_block_production_routes_and_correct_entrance_floor():
    data = read_indoor(ROOT / "data/indoor/ilc.json")
    assert data.status == "draft" and data.reviewed_at is None
    south = next(n for n in data.nodes if n.id == "ilc-entrance-south")
    assert south.floor_id == "2" and "Southwest" in south.label
    assert all(n.id != "ilc-entrance-west" for n in data.nodes)
    assert not data.portals
    assert not any(south.id in (e.start, e.end) for e in data.edges)
    with pytest.raises(RoutingError) as error:
        IndoorEngine(data)
    assert error.value.code == "indoor_not_ready"
    with TestClient(create_app()) as client:
        status = next(
            b for b in client.get("/indoor/status").json()["buildings"] if b["building_id"] == "ilc"
        )
        assert status["routable"] is False and status["room_routable"] is False
        assert "WITHDRAWN" in status["review_notes"]
        response = client.post(
            "/indoor/route",
            json={
                "building_id": "ilc",
                "start_node_id": south.id,
                "end_node_id": "ilc-source-n151-f2",
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "indoor_not_ready"


def test_production_maps_cover_all_source_destinations():
    library = read_indoor(ROOT / "data/indoor/library.json")
    ilc = read_indoor(ROOT / "data/indoor/ilc.json")

    assert sum(node.kind == "room" for node in library.nodes) == 27
    assert sum(node.kind == "room" for node in ilc.nodes) == 16


def test_public_floorplan_manifest_covers_available_library_and_ilc_plans():
    manifest = json.loads((ROOT / "data/indoor/public_floorplans.json").read_text(encoding="utf-8"))
    library = [row for row in manifest["plans"] if row["building_id"] == "library"]
    ilc = [row for row in manifest["plans"] if row["building_id"] == "ilc"]

    assert len(library) == 26
    assert {row["floor_id"] for row in ilc} == {"1", "2"}


def test_old_ilc_trace_cannot_overwrite_field_corrections(tmp_path):
    from scripts.trace_public_ilc_topology import trace

    original = (ROOT / "data/indoor/ilc.json").read_bytes()
    path = tmp_path / "ilc.json"
    path.write_bytes(original)
    with pytest.raises(ValueError, match="withdrawn"):
        trace(path)
    assert path.read_bytes() == original


def test_unlocated_north_elevator_is_recorded_without_a_guessed_shaft():
    review = json.loads((ROOT / "data/reviews/ilc-field-review.json").read_text())
    north = next(row for row in review["observations"] if row["id"] == "north-elevator")
    assert north["floors_served"] == ["1", "2"]
    assert north["position"] is None and north["matches_existing_asset"] is None
