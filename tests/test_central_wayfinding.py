from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, box

from campus_notices.cache import atomic_json
from campus_notices.central_plans import CONFERENCE_PROGRAM, HOTEL_DIRECTIONS
from campus_notices.plan_integrity import REVIEWED_HASHES
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.models import Closure
from campus_routing.plan_wayfinding import PlanWayfindingRequest, plan_directions
from scripts.build_campus_center_plans import build
from scripts.build_central_wayfinding import student_union
from scripts.make_demo import make_demo_graph


def records():
    sizes = {
        "first-floor.png": (497, 601),
        "second-floor.jpg": (679, 635),
        "eight-floor.jpg": (497, 583),
        "ten-11-floor.jpg": (497, 547),
    }
    return [
        dict(id=k, url="https://example.com/" + k, sha256="a" * 64, width=w, height=h)
        for k, (w, h) in sizes.items()
    ]


def request(a, b):
    return PlanWayfindingRequest(start_node_id=a, end_node_id=b, accept_drawing_only=True)


def test_public_campus_center_has_selected_six_floor_coverage_and_no_residence_gate():
    data = build(records())
    assert set(data.floor_sources) == {"1", "2", "8", "9", "10", "11"}
    assert not data.resident_access_required
    result = plan_directions(data, request("near-801", "marriott-foyer"))
    assert any(s["kind"] == "elevator" for s in result["steps"])
    assert result["coordinate_system"] == "image_pixels" and result["distance_m"] is None
    assert plan_directions(data, request("west-entry-2", "u-pub-approach"))["steps"]
    with pytest.raises(RoutingError, match="No drawing connection"):
        plan_directions(data, request("west-entry-2", "near-801"))


def test_first_floor_path_goes_around_room_163_and_upper_core_does_not_cross_restrooms():
    data = build(records())
    nodes = {n.id: n for n in data.nodes}
    for e in data.connections:
        a, b = nodes[e.start], nodes[e.end]
        if a.floor_id == b.floor_id == "1":
            assert not LineString([(a.x, a.y), (b.x, b.y)]).intersects(box(276, 328, 348, 393))
        if a.floor_id == b.floor_id == "8":
            assert not LineString([(a.x, a.y), (b.x, b.y)]).intersects(box(30, 304, 82, 345))


HTML = """<p>Room 235 is between Craft Center and Black Box Theater on the lower level.
The elevators are past the SORC office and to the left.</p>"""


def test_student_union_uses_official_landmarks_without_fabricated_geometry():
    data = student_union(HTML)
    result = plan_directions(data, request("sorc-landmark", "gallery-235"))
    assert result["coordinate_system"] == "landmarks_only"
    assert all(s["geometry"] is None and s["from_position"] is None for s in result["steps"])
    assert "left" in result["steps"][0]["instruction"]
    assert result["steps"][1]["kind"] == "elevator"
    assert "exact turns" in result["steps"][-1]["instruction"]
    with pytest.raises(ValueError, match="source changed"):
        student_union("<p>New page without the directions</p>")


def test_catalog_lists_only_valid_maps_and_public_route_needs_no_resident_flag(tmp_path):
    data = student_union(HTML)
    atomic_json(tmp_path / "student-union.json", data.model_dump(mode="json"))
    atomic_json(tmp_path / "coverage-audit.json", dict(buildings=[]))
    with TestClient(
        create_app(engine=RoutingEngine(make_demo_graph()), plan_wayfinding_dir=tmp_path)
    ) as c:
        rows = c.get("/plan-wayfinding").json()["buildings"]
        assert len(rows) == 1 and rows[0]["building_id"] == "student-union"
        response = c.post(
            "/plan-wayfinding/student-union",
            json=request("sorc-landmark", "gallery-235").model_dump(),
        )
        assert response.status_code == 200


def concourse_sources():
    return {
        "cc-2026-conference-program": dict(
            url=CONFERENCE_PROGRAM, sha256=REVIEWED_HASHES["cc-2026-conference-program.pdf"]
        ),
        "cc-hotel-directions": dict(url=HOTEL_DIRECTIONS, sha256="b" * 64),
    }


def test_annotated_concourse_source_enables_both_directions_and_one_continuous_ride():
    data = build(records(), concourse_sources())
    forward = plan_directions(data, request("west-entry-2", "marriott-foyer"))
    ride = [s for s in forward["steps"] if s["kind"] == "elevator"]
    assert len(ride) == 1 and (ride[0]["from_floor"], ride[0]["to_floor"]) == ("2", "11")
    assert ride[0]["geometry"] is None
    backward = plan_directions(data, request("marriott-foyer", "west-entry-2"))
    assert backward["steps"][-1]["to_node_id"] == "west-entry-2"
    assert "annotation_url" in data.floor_sources["2"]
    first_floor = plan_directions(data, request("west-entry-2", "elevator-1"))
    assert first_floor["graph_steps"][-1]["from_node_id"] == "elevator-2"
    assert first_floor["graph_steps"][-1]["to_node_id"] == "elevator-1"
    changed = concourse_sources()
    changed["cc-2026-conference-program"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="edition differs"):
        build(records(), changed)


def test_concourse_bank_outage_blocks_upstairs_but_preserves_concourse_route():
    data = build(records(), concourse_sources())
    now = datetime.now(UTC)
    closure = Closure(
        lat=0,
        lng=0,
        radius=1,
        type="elevator",
        status="closed",
        source="official",
        asset_id="umass-elevator-141",
        building_id="campus-center",
        start_time=now - timedelta(minutes=1),
        end_time=now + timedelta(hours=1),
        last_confirmed=now,
    )
    req = request("west-entry-2", "marriott-foyer").model_copy(update={"closures": [closure]})
    with pytest.raises(RoutingError, match="No drawing connection"):
        plan_directions(data, req, now=now)
    local = request("west-entry-2", "u-pub-approach").model_copy(update={"closures": [closure]})
    assert plan_directions(data, local, now=now)["steps"]
