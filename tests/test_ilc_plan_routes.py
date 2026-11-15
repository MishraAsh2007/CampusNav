import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campus_routing.api import create_app
from campus_routing.engine import RoutingError
from campus_routing.models import Closure
from campus_routing.plan_wayfinding import PlanWayfindingMap, PlanWayfindingRequest, plan_directions

ROOT = Path(__file__).resolve().parents[1]


def data():
    return PlanWayfindingMap.model_validate_json(
        (ROOT / "data/plan_wayfinding/ilc.json").read_text(encoding="utf-8")
    )


def request(**updates):
    return PlanWayfindingRequest.model_validate(
        dict(
            start_node_id="ilc-entrance-south",
            end_node_id="ilc-door-n155-f1",
            accept_drawing_only=True,
            **updates,
        )
    )


def test_every_listed_destination_reachable_from_corrected_floor_2_entrance():
    plan = data()
    assert set(plan.floor_sources) == {"1", "2"}
    nodes = {n.id: n for n in plan.nodes}
    assert nodes["ilc-entrance-south"].floor_id == "2"
    for node in plan.nodes:
        if node.kind != "room":
            continue
        req = PlanWayfindingRequest(
            start_node_id="ilc-entrance-south", end_node_id=node.id, accept_drawing_only=True
        )
        result = plan_directions(plan, req)
        assert result["steps"][-1]["to_node_id"] == node.id
        assert result["distance_m"] is None and result["max_grade"] is None
        assert any(s["kind"] == "elevator" for s in result["steps"]) == (node.floor_id == "1")
        reverse = plan_directions(
            plan,
            req.model_copy(update={"start_node_id": node.id, "end_node_id": "ilc-entrance-south"}),
        )
        assert reverse["steps"][-1]["to_floor"] == "2"


def test_three_shafts_offer_alternatives_and_all_closed_blocks_floor_change():
    plan = data()
    assets = {e.asset_id for e in plan.connections if e.kind == "elevator"}
    assert assets == {"ilc-lift-north", "ilc-lift-central-q", "ilc-lift-central-p"}
    now = datetime.now(UTC)
    blocked = []
    for _ in range(3):
        result = plan_directions(plan, request(closures=blocked))
        ride = next(s for s in result["steps"] if s["kind"] == "elevator")
        assert ride["asset_id"] not in {c.asset_id for c in blocked}
        blocked.append(
            Closure(
                lat=42.391,
                lng=-72.526,
                radius=3,
                type="elevator",
                status="closed",
                source="community",
                building_id="ilc",
                asset_id=ride["asset_id"],
                start_time=now - timedelta(minutes=1),
                end_time=now + timedelta(hours=1),
                last_confirmed=now,
            )
        )
    with pytest.raises(RoutingError, match="No drawing connection"):
        plan_directions(plan, request(closures=blocked))


def test_default_api_serves_same_fingerprint_images_and_requires_consent():
    with TestClient(create_app()) as client:
        catalog = client.get("/plan-wayfinding").json()
        assert any(b["building_id"] == "ilc" for b in catalog["buildings"])
        for floor, source in data().floor_sources.items():
            response = client.get(f"/plan-wayfinding/ilc/floors/{floor}/image")
            assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
            assert hashlib.sha256(response.content).hexdigest() == source["source_sha256"]
        body = request().model_dump(mode="json")
        assert client.post("/plan-wayfinding/ilc", json=body).status_code == 200
        assert (
            client.post(
                "/plan-wayfinding/ilc", json=body | {"accept_drawing_only": False}
            ).status_code
            == 409
        )


def test_outdoor_arrival_and_journey_use_the_same_floor_2_threshold():
    from scripts.build_ilc_portal import build_portal

    portal = build_portal()
    assert portal.floor_id == "2"
    assert portal.entrance_id == "osm-entrance-6382267406"
    assert portal.door_type == "push-button"
    assert portal.door_evidence.source == "community_peer_report"
    assert portal.physical_verification is False
    with TestClient(create_app()) as client:
        origin = dict(lat=42.3908237, lng=-72.5262754)
        destination = dict(lat=42.391, lng=-72.526, building_id="ilc")
        response = client.post(
            "/plan",
            json=dict(
                origin=origin,
                destination=destination,
                max_grade=7,
                need_automatic_door=True,
                prefer_indoor_entrance=True,
            ),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["end_entrance"]["id"] == portal.entrance_id
        assert result["end_entrance"]["door_type"] == "push-button"
        assert result["end_entrance"]["current_operation_verified"] is False
        assert result["accessible"]["properties"]["max_grade"] <= 7
        assert result["indoor_arrival"]["node_id"] == "ilc-entrance-south"
        assert result["indoor_arrival"]["floor_id"] == "2"
        journey = client.post(
            "/journey",
            json=dict(
                origin=dict(kind="outdoor", **origin),
                destination=dict(kind="drawing", building_id="ilc", node_id="ilc-door-n155-f1"),
                max_grade=8,
                accept_drawing_only=True,
            ),
        )
        assert journey.status_code == 200, journey.text
        legs = journey.json()["legs"]
        transition = next(leg for leg in legs if leg["kind"] == "portal")
        assert transition["indoor_node_id"] == "ilc-entrance-south"
        indoor = next(leg for leg in legs if leg["kind"] == "indoor")
        assert indoor["steps"][0]["from_floor"] == "2"
        assert indoor["steps"][-1]["to_floor"] == "1"


def test_offset_gis_arrival_does_not_silently_become_the_southwest_door():
    with TestClient(create_app()) as client:
        result = client.post(
            "/plan",
            json=dict(
                origin=dict(lat=42.3907945, lng=-72.5262648),
                destination=dict(
                    lat=42.39078755,
                    lng=-72.52624643,
                    building_id="ilc",
                    entrance_id="umass-legacy-entrance-56",
                ),
                max_grade=8,
                prefer_indoor_entrance=True,
            ),
        ).json()
        assert result["accessible"] is not None
        assert result.get("indoor_arrival") is None


def test_portal_preference_does_not_relax_slope_requirements():
    with TestClient(create_app()) as client:
        result = client.post(
            "/plan",
            json=dict(
                origin=dict(lat=42.3908237, lng=-72.5262754),
                destination=dict(lat=42.391, lng=-72.526, building_id="ilc"),
                max_grade=5,
                prefer_indoor_entrance=True,
            ),
        ).json()
        assert result.get("indoor_arrival") is None
        if result["accessible"]:
            assert result["accessible"]["properties"]["max_grade"] <= 5


def test_confirmed_opener_does_not_bypass_slope_limit_and_metadata_is_not_cached():
    with TestClient(create_app()) as client:
        for path in ("/indoor/status", "/indoor/maps/ilc", "/plan-wayfinding/ilc"):
            assert client.get(path).headers["Cache-Control"] == "no-store"
        result = client.post(
            "/plan",
            json=dict(
                origin=dict(lat=42.3907945, lng=-72.5262648),
                destination=dict(lat=42.391, lng=-72.526, building_id="ilc"),
                max_grade=6,
                need_automatic_door=True,
                prefer_indoor_entrance=True,
            ),
        ).json()
        assert result["accessible"] is not None
        assert result["indoor_arrival"] is None
        assert result["indoor_handoff"]["status"] == "unavailable"
        assert "slope limit" in result["indoor_handoff"]["message"]
        assert "automatic-door evidence" not in result["indoor_handoff"]["message"]
        assert "none of the eligible mapped entrances" not in result["indoor_handoff"]["message"]
