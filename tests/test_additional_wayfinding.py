from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, box

from campus_notices.cache import atomic_json
from campus_notices.plan_integrity import REVIEWED_HASHES
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.models import Closure
from campus_routing.plan_wayfinding import PlanWayfindingRequest, plan_directions
from scripts.audit_plan_wayfinding import audit
from scripts.build_additional_wayfinding import BUILDERS, checked
from scripts.make_demo import make_demo_graph

FLOORS = {"old-chapel": "12", "north-d": "12345", "goodell": "3456"}
TARGETS = {
    "old-chapel": "entry-threshold-1",
    "north-d": "exit-threshold-1",
    "goodell": "west-entry-3",
}
STARTS = {
    "old-chapel": "stage-ramp-approach-2",
    "north-d": "apartment-513-5",
    "goodell": "student-success-east-6",
}
BANKS = {
    "old-chapel": "old-chapel-elevator-bank",
    "north-d": "umass-elevator-148",
    "goodell": "umass-elevator-120",
}


def data_for(building):
    return BUILDERS[building](
        {
            f: dict(url="https://example.com/official-plan", sha256="a" * 64)
            for f in FLOORS[building]
        }
    )


def request(a, b, **updates):
    return PlanWayfindingRequest(
        **(
            dict(
                start_node_id=a,
                end_node_id=b,
                accept_drawing_only=True,
                resident_access_confirmed=True,
            )
            | updates
        )
    )


@pytest.mark.parametrize("building", BUILDERS)
def test_every_landmark_can_reach_and_return_from_entry_on_documented_floors(building):
    data = data_for(building)
    report = audit(data, TARGETS[building])
    assert set(report["floors"]) == set(FLOORS[building])
    assert all(n["reachable"] and n["returnable"] for n in report["nodes"])
    assert set(e.kind for e in data.connections) <= {"corridor", "door", "elevator"}
    result = plan_directions(data, request(STARTS[building], TARGETS[building]))
    assert result["physical_verification"] is False
    assert result["distance_m"] is None and result["max_grade"] is None
    rides = [s for s in result["steps"] if s["kind"] == "elevator"]
    assert len(rides) == 1  # No intermediate floor exits on a multi-stop ride.
    assert rides[0]["from_floor"] == FLOORS[building][-1]
    assert rides[0]["to_floor"] == FLOORS[building][0]
    assert rides[0]["geometry"] is None
    for edge in data.connections:
        if edge.kind == "elevator":
            assert edge.asset_id == BANKS[building] and edge.served_floor_evidence


@pytest.mark.parametrize("building", BUILDERS)
def test_bank_closure_blocks_cross_floor_but_keeps_same_floor_and_ignores_expired(building):
    data = data_for(building)
    now = datetime.now(UTC)
    c = Closure(
        lat=0,
        lng=0,
        radius=1,
        type="elevator",
        status="closed",
        source="official",
        building_id=building,
        asset_id=BANKS[building],
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        last_confirmed=now,
    )
    with pytest.raises(RoutingError, match="No drawing connection"):
        plan_directions(data, request(STARTS[building], TARGETS[building], closures=[c]), now=now)
    assert plan_directions(
        data, request(f"elevator-{FLOORS[building][0]}", TARGETS[building], closures=[c]), now=now
    )["steps"]
    for update in [dict(end_time=now), dict(building_id="another-building")]:
        assert plan_directions(
            data,
            request(STARTS[building], TARGETS[building], closures=[c.model_copy(update=update)]),
            now=now,
        )["steps"]


def test_resident_gate_and_no_invented_bedroom_or_unknown_unit_destinations():
    north = data_for("north-d")
    with pytest.raises(RoutingError, match="permitted"):
        plan_directions(
            north, request(STARTS["north-d"], TARGETS["north-d"], resident_access_confirmed=False)
        )
    for floor in "2345":
        units = [n for n in north.nodes if n.id.startswith("apartment-") and n.floor_id == floor]
        assert len(units) == 11
        assert all("Shared hall outside" in n.label for n in units)
        assert all(n.x == 299 or n.y == 430 for n in units)
    for building in ("old-chapel", "goodell"):
        assert plan_directions(
            data_for(building),
            request(STARTS[building], TARGETS[building], resident_access_confirmed=False),
        )["steps"]
    with pytest.raises(RoutingError, match="Choose a destination"):
        plan_directions(north, request("apartment-501-5", TARGETS["north-d"]))


def assert_avoids(data, floor, excluded):
    nodes = {n.id: n for n in data.nodes}
    for edge in data.connections:
        a, b = nodes[edge.start], nodes[edge.end]
        if a.floor_id == b.floor_id == floor:
            segment = LineString([(a.x, a.y), (b.x, b.y)])
            assert not segment.intersects(excluded), edge.id


def test_chapel_avoids_display_case_void_and_undocumented_stage_ramp():
    data = data_for("old-chapel")
    assert_avoids(data, "1", box(260, 335, 294, 535))
    assert_avoids(data, "2", box(587, 385, 674, 547))
    assert_avoids(data, "2", box(180, 245, 219, 330))


def test_goodell_avoids_shafts_voids_stairs_and_uncertain_north_bridges():
    data = data_for("goodell")
    for floor, shaft in {
        "3": (470, 508, 500, 543),
        "4": (480, 541, 510, 574),
        "5": (446, 505, 475, 539),
        "6": (446, 524, 475, 560),
    }.items():
        assert_avoids(data, floor, box(*shaft))
    for region in [(490, 300, 652, 445), (680, 310, 820, 450), (660, 665, 925, 790)]:
        assert_avoids(data, "6", box(*region))
    assert_avoids(data, "5", box(600, 240, 668, 265))
    assert_avoids(data, "6", box(772, 239, 779, 285))


@pytest.mark.parametrize("building", BUILDERS)
def test_public_api_lists_and_routes_each_map_and_requires_drawing_acceptance(tmp_path, building):
    data = data_for(building)
    atomic_json(tmp_path / f"{building}.json", data.model_dump(mode="json"))
    client = TestClient(
        create_app(engine=RoutingEngine(make_demo_graph()), plan_wayfinding_dir=tmp_path)
    )
    catalog = client.get("/plan-wayfinding")
    assert catalog.status_code == 200
    assert building in catalog.text
    response = client.get(f"/plan-wayfinding/{building}")
    assert response.status_code == 200 and STARTS[building] in response.text
    body = request(STARTS[building], TARGETS[building]).model_dump(mode="json")
    result = client.post(f"/plan-wayfinding/{building}", json=body)
    assert (
        result.status_code == 200 and result.json()["steps"][-1]["to_node_id"] == TARGETS[building]
    )
    body["accept_drawing_only"] = False
    assert client.post(f"/plan-wayfinding/{building}", json=body).status_code == 409


def test_changed_source_edition_cannot_be_used_with_old_geometry(tmp_path):
    path = tmp_path / "changed.pdf"
    path.write_bytes(b"a changed source edition")
    for name in [
        "673-01.pdf",
        "673-02.03.04.05.pdf",
        "old-chapel-tour-guide.pdf",
        "goodell-march-2025.jpg",
    ]:
        assert name in REVIEWED_HASHES
        with pytest.raises(ValueError, match="re-inspect"):
            checked(path, name)


def test_floor_images_are_limited_to_the_configured_pilot_source_directory(tmp_path):
    folder = tmp_path / "plans"
    images = folder / "sources"
    images.mkdir(parents=True)
    png = images / "floor.png"
    png.write_bytes(b"source-image-fixture")
    data = data_for("north-d")
    data.floor_sources["1"]["local_image"] = str(png)
    atomic_json(folder / "north-d.json", data.model_dump(mode="json"))
    client = TestClient(create_app(plan_wayfinding_dir=folder))
    result = client.get("/plan-wayfinding/north-d/floors/1/image")
    assert result.status_code == 200 and result.headers["content-type"] == "image/png"
    assert result.content == png.read_bytes()
    # A graph file cannot turn this endpoint into a general private-file server.
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"PRIVATE_FILE")
    data.floor_sources["1"]["local_image"] = str(outside)
    atomic_json(folder / "north-d.json", data.model_dump(mode="json"))
    assert client.get("/plan-wayfinding/north-d/floors/1/image").status_code == 404
