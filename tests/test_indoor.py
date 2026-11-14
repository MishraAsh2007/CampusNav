from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from campus_notices.cache import atomic_json
from campus_notices.community import ReportStore, UserReport
from campus_notices.indoor_sources import (
    SOURCES,
    create_indoor_drafts,
    parse_source,
    refresh_indoor_sources,
)
from campus_notices.models import Impact, Location, Notice
from campus_notices.pipeline import _resolve
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.indoor import IndoorEngine, IndoorMap, IndoorRouteRequest
from campus_routing.journey import JourneyRequest, plan_journey
from campus_routing.models import Closure, Coordinate, RouteRequest
from scripts.demo_indoor import NOW, demo_map, lift_closure
from scripts.export_indoor_assets import export_assets
from scripts.import_indoor import import_map
from scripts.make_demo import make_demo_graph


@pytest.fixture
def engine():
    return IndoorEngine(demo_map(), allow_synthetic=True)


def request(**changes):
    return IndoorRouteRequest.model_validate(
        dict(building_id="demo-building", start_node_id="entrance", end_node_id="room-201")
        | changes
    )


def test_elevator_outage_changes_shaft_then_no_route_without_relaxing(engine):
    a = engine.route(request(), now=NOW)
    b = engine.route(request(closures=[lift_closure()]), now=NOW)
    assert a["transitions"][0]["asset_id"] == "demo-lift-a"
    assert b["transitions"][0]["asset_id"] == "demo-lift-b"
    assert a["total_distance"] == 14 and b["total_distance"] == 34
    assert b["floor_sequence"] == ["1", "2"] and not b["uses_stairs"]
    assert len(b["steps"]) == len(b["segments"]) + len(b["transitions"])
    closed = [lift_closure(), lift_closure("demo-lift-b")]
    with pytest.raises(RoutingError, match="No indoor route"):
        engine.route(request(closures=closed), now=NOW)
    standard = engine.route(request(closures=closed, no_stairs=False, max_grade=None), now=NOW)
    assert standard["uses_stairs"] and not standard["uses_elevator"]
    grade_limited = engine.route(request(closures=closed, no_stairs=False), now=NOW)
    assert grade_limited["uses_stairs"]
    assert engine.route(request(), now=NOW) == a  # request-local closures


def test_expired_future_and_other_building_outages_do_not_remove_lift(engine):
    for overrides in [
        dict(end_time=NOW),
        dict(start_time=NOW + timedelta(minutes=1)),
        dict(building_id="another-building"),
    ]:
        result = engine.route(request(closures=[lift_closure(**overrides)]), now=NOW)
        assert result["transitions"][0]["asset_id"] == "demo-lift-a"


def test_same_xy_is_not_a_connection_between_floors():
    data = demo_map().model_dump(mode="json")
    data["edges"] = [e for e in data["edges"] if e["kind"] not in ("elevator", "steps")]
    engine = IndoorEngine(IndoorMap.model_validate(data), allow_synthetic=True)
    with pytest.raises(RoutingError, match="No indoor route"):
        engine.route(request(), now=NOW)


def test_floor_specific_closure_does_not_disable_same_asset_on_another_floor(engine):
    c = lift_closure("demo-hall", type="path", floor_id="1")
    result = engine.route(request(start_node_id="hall2", closures=[c]), now=NOW)
    assert result["total_distance"] == 2
    with pytest.raises(RoutingError, match="No indoor route"):
        engine.route(request(closures=[c]), now=NOW)


def test_exact_unknown_asset_does_not_fall_back_to_nearby_elevators(engine):
    result = engine.route(request(closures=[lift_closure("unmapped-shaft")]), now=NOW)
    assert result["transitions"][0]["asset_id"] == "demo-lift-a"
    assert any("not mapped" in w for w in result["warnings"])


def test_unknown_access_and_grade_require_explicit_opt_in():
    data = demo_map().model_dump(mode="json")
    data["edges"][0].update(step_free=None, grade_percent=None)
    engine = IndoorEngine(IndoorMap.model_validate(data), allow_synthetic=True)
    with pytest.raises(RoutingError):
        engine.route(request(), now=NOW)
    result = engine.route(request(allow_unknown_access=True, allow_unknown_grade=True), now=NOW)
    assert result["max_grade"] is None
    assert any("Step-free access is unknown" in w for w in result["warnings"])


def test_review_and_synthetic_gates():
    data = demo_map()
    with pytest.raises(RoutingError, match="Demo maps"):
        IndoorEngine(data)
    with pytest.raises(RoutingError, match="awaiting review"):
        IndoorEngine(data.model_copy(update={"status": "draft"}), allow_synthetic=True)
    body = data.model_dump(mode="json")
    body["edges"][-1]["kind"] = "corridor"
    with pytest.raises(ValidationError, match="change floors"):
        IndoorMap.model_validate(body)


def test_complete_outdoor_portal_indoor_journey_and_blocked_portal(engine):
    outdoor = RoutingEngine(make_demo_graph())
    body = dict(
        origin=dict(kind="outdoor", lat=42.391, lng=-72.528),
        destination=dict(kind="indoor", building_id="demo-building", node_id="room-201"),
        closures=[lift_closure().model_dump()],
    )
    journey = plan_journey(outdoor, lambda _: engine, JourneyRequest.model_validate(body), now=NOW)
    assert [leg["kind"] for leg in journey["legs"]] == ["outdoor", "portal", "indoor"]
    assert journey["legs"][-1]["node_path"][-1] == "room-201"
    assert journey["legs"][-1]["transitions"][0]["asset_id"] == "demo-lift-b"
    c = lift_closure(None, type="path", floor_id="1")
    body["closures"] = [c.model_dump()]
    with pytest.raises(RoutingError, match="No complete journey"):
        plan_journey(outdoor, lambda _: engine, JourneyRequest.model_validate(body), now=NOW)


def test_floor_scoped_issue_does_not_close_outdoor_paths():
    engine = RoutingEngine(make_demo_graph())
    req = RouteRequest(
        start=Coordinate(lat=42.391, lng=-72.528), end=Coordinate(lat=42.392, lng=-72.528)
    )
    baseline = engine.route(req, now=NOW)
    c = lift_closure(None, type="path", floor_id="2", radius=1000)
    result = engine.route(req.model_copy(update={"closures": [c]}), now=NOW)
    assert result.geometry == baseline.geometry


def test_role3_publishing_preserves_explicit_asset_building_and_floor():
    notice = Notice(
        id="n",
        source_id="test",
        source_ref="https://example.org/notice",
        building="Demo",
        text="The elevator A is closed.",
        observed_at=NOW,
        start_time=NOW - timedelta(hours=1),
        end_time=NOW + timedelta(hours=1),
    )
    location = Location(
        id="mapped-lift",
        name="Elevator A",
        lat=42.392,
        lng=-72.528,
        radius=4,
        type="elevator",
        building_aliases=["Demo"],
        asset_phrases=["elevator A"],
        reviewed=True,
        evidence="Synthetic mapping test",
        asset_id="demo-lift-a",
        building_id="demo-building",
        floor_id="2",
    )
    impact = Impact(type="elevator", status="closed", evidence=notice.text)
    closure, _, errors = _resolve(notice, impact, [location], "rules", NOW)
    assert not errors
    assert closure.asset_id == "demo-lift-a" and closure.floor_id == "2"
    assert closure.building_id == "demo-building"


def test_api_exposes_floor_metadata_and_rejects_unpublished_or_synthetic_maps(tmp_path):
    data = demo_map()
    atomic_json(tmp_path / "demo-building.json", data.model_dump(mode="json"))
    with TestClient(create_app(engine=RoutingEngine(make_demo_graph()), indoor_dir=tmp_path)) as c:
        assert c.get("/indoor/maps/demo-building").json()["floors"][1]["id"] == "2"
        assert not c.get("/indoor/status").json()["buildings"][0]["routable"]
        assert c.post("/indoor/route", json=request().model_dump(mode="json")).status_code == 409
        assert c.get("/indoor/maps/unknown").status_code == 404
        assert c.get("/indoor/maps/bad.id").status_code == 422
    original = (tmp_path / "demo-building.json").read_bytes()
    with pytest.raises(ValueError, match="non-synthetic"):
        import_map(tmp_path / "demo-building.json", tmp_path, tmp_path / "unused.json")
    assert (tmp_path / "demo-building.json").read_bytes() == original


LIBRARY = (
    "<table><tr><th>Floor</th><th>Services</th><th>Features</th></tr>"
    "<tr><td>E</td><td>Info Desk</td><td>Service Desk</td></tr></table>"
)
CARD = (
    '<div class="analytics-card" data-loc="31"><img src="/media/maps/lower.png">'
    "<h1>W. E. B. Du Bois Library</h1><h2>Lower Level</h2></div>"
)
CC = (
    "<table><tr><th>Room</th><th>Floor Plans &amp; Capacity Chart</th></tr>"
    "<tr><td>801</td><td>8th Floor Campus Center</td></tr>"
    "<tr><td>999</td><td>Unknown</td></tr></table>"
)


def test_floorplan_scrape_deduplicates_cards_without_inventing_routing_edges():
    rows = parse_source("library-floorplans", CARD + CARD, NOW)
    assert (
        len(rows) == 1 and rows[0]["image_url"] == "https://umass.stackmap.com/media/maps/lower.png"
    )
    assert rows[0]["floor_label"] == "Lower Level" and rows[0]["routing_eligible"] is False
    rooms = parse_source("campus-center-directory", CC, NOW)
    assert len(rooms) == 1 and rooms[0]["floor_label"] == "8"
    assert "geometry" not in rooms[0]  # room number does not supply coordinates


def test_indoor_scrape_failure_keeps_prior_source_timestamp(tmp_path):
    payloads = {
        "library-directory": LIBRARY,
        "library-floorplans": CARD,
        "campus-center-directory": CC,
    }
    fail = False

    def handler(req):
        key = next((k for k, url in SOURCES.items() if url == str(req.url)), None)
        if key not in payloads:
            return httpx.Response(503)
        if fail and key == "library-floorplans":
            return httpx.Response(401)
        return httpx.Response(200, text=payloads[key], headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = tmp_path / "sources.json"
        first = refresh_indoor_sources(path, client=client, now=NOW)
        fail = True
        second = refresh_indoor_sources(path, client=client, now=NOW + timedelta(hours=1))
    old = first["sources"]["library-floorplans"]
    new = second["sources"]["library-floorplans"]
    assert new["mode"] == "cache" and new["observed_at"] == old["observed_at"]
    assert len(second["records"]) == 3 and second["routing_eligible"] is False


def test_closure_floor_requires_building():
    with pytest.raises(ValidationError, match="requires building_id"):
        Closure.model_validate(lift_closure().model_dump() | {"floor_id": "1", "building_id": None})


def test_drafts_expose_floor_images_but_never_route_or_overwrite_authored_work(tmp_path):
    records = parse_source("library-floorplans", CARD, NOW)
    create_indoor_drafts({"records": records}, tmp_path)
    path = tmp_path / "library.json"
    data = IndoorMap.model_validate_json(path.read_text())
    assert data.status == "draft" and not data.edges
    assert str(data.floors[0].image_url).endswith("lower.png")
    path.write_text("manual edit in progress")
    assert not create_indoor_drafts({"records": records}, tmp_path)
    assert path.read_text() == "manual edit in progress"


def test_registry_export_keeps_asset_identity_and_unrelated_locations(tmp_path):
    data = demo_map().model_dump(mode="json")
    data["synthetic"] = False  # Isolated test input; never published to the campus directory.
    path, registry = tmp_path / "map.json", tmp_path / "registry.json"
    atomic_json(path, data)
    assert export_assets(path, registry) == 3
    import json

    rows = json.loads(registry.read_text())
    assert rows[0]["asset_id"] == "demo-lift-a"
    assert rows[0]["building_id"] == "demo-building"
    assert rows[0]["asset_phrases"] == ["demo-lift-a"]


def test_community_restoration_does_not_erase_report_on_another_floor(tmp_path):
    store = ReportStore(tmp_path / "reports.json")
    base = dict(
        lat=42.392,
        lng=-72.528,
        type="path",
        status="broken",
        timestamp=NOW,
        building_id="demo-building",
        asset_id="demo-hall",
    )
    store.submit(UserReport(**base, floor_id="1"), now=NOW)
    store.submit(UserReport(**base, floor_id="2"), now=NOW)
    store.submit(UserReport(**(base | {"status": "working"}), floor_id="1"), now=NOW)
    assert [r["floor_id"] for r in store.active(NOW)] == ["2"]


def test_reviewed_api_routes_and_accepts_scoped_report(tmp_path):
    data = demo_map().model_dump(mode="json")
    data["synthetic"] = False  # TestClient only; actual example stays synthetic.
    atomic_json(tmp_path / "demo-building.json", data)
    with TestClient(
        create_app(
            engine=RoutingEngine(make_demo_graph()),
            indoor_dir=tmp_path,
            community_path=tmp_path / "community.json",
        )
    ) as client:
        result = client.post("/indoor/route", json=request().model_dump(mode="json"))
        assert result.status_code == 200
        assert result.json()["transitions"][0]["asset_id"] == "demo-lift-a"
        report = dict(
            lat=42.392,
            lng=-72.528,
            type="elevator",
            status="broken",
            timestamp=datetime.now(UTC).isoformat(),
            asset_id="demo-lift-a",
            building_id="demo-building",
        )
        assert client.post("/reports", json=report).status_code == 201
        assert client.post("/reports", json=report | {"asset_id": "not-mapped"}).status_code == 422


def test_bound_portal_node_cannot_teleport_to_coincident_other_component():
    graph = make_demo_graph()
    graph.add_node(90, lat=42.392, lng=-72.528)
    graph.add_node(91, lat=42.3921, lng=-72.528)
    graph.add_edge(
        90,
        91,
        length=11,
        grade_percent=0,
        kind="path",
        coordinates=[[-72.528, 42.392], [-72.528, 42.3921]],
    )
    engine = RoutingEngine(graph)
    start, end = Coordinate(lat=42.392, lng=-72.528), Coordinate(lat=42.391, lng=-72.528)
    req = RouteRequest(start=start, end=end)
    with pytest.raises(RoutingError, match="No route"):
        engine.route_many(req, [start], [end], start_node_ids=[90], end_node_ids=[1], now=NOW)


def test_private_corridor_is_never_an_accessible_fallback():
    data = demo_map().model_dump(mode="json")
    data["edges"][0]["public_access"] = False
    engine = IndoorEngine(IndoorMap.model_validate(data), allow_synthetic=True)
    with pytest.raises(RoutingError, match="No indoor route"):
        engine.route(request(allow_unknown_access=True, no_stairs=False, max_grade=None), now=NOW)


def test_journey_changes_entrance_when_a_floor_specific_entry_is_closed():
    data = demo_map().model_dump(mode="json")
    source = data["sources"][0]["id"]
    data["nodes"].append(
        dict(
            id="upper-entry",
            label="Synthetic upper entrance",
            kind="entrance",
            floor_id="2",
            x=1,
            y=0,
            position=dict(lat=42.391, lng=-72.528001),
            source_id=source,
        )
    )
    data["edges"].append(
        dict(
            id="upper-room",
            start="upper-entry",
            end="room-201",
            kind="door",
            geometry=[[1, 0], [0, 0]],
            length_m=1,
            public_access=True,
            step_free=True,
            grade_percent=0,
            door_type="automatic",
            source_id=source,
            evidence="Synthetic connection for alternate-entrance test.",
        )
    )
    data["portals"].append(
        dict(
            id="upper-portal",
            indoor_node_id="upper-entry",
            outdoor_node_id=1,
            geometry=[[-72.528001, 42.391], [-72.528, 42.391]],
            length_m=0.1,
            public_access=True,
            step_free=True,
            grade_percent=0,
            door_type="automatic",
            source_id=source,
            evidence="Synthetic upper portal to demo graph node 1.",
        )
    )
    engine = IndoorEngine(IndoorMap.model_validate(data), allow_synthetic=True)
    outdoor = RoutingEngine(make_demo_graph())
    req = JourneyRequest.model_validate(
        dict(
            origin=dict(kind="outdoor", lat=42.391, lng=-72.528),
            destination=dict(kind="indoor", building_id="demo-building", node_id="room-201"),
        )
    )
    before = plan_journey(outdoor, lambda _: engine, req, now=NOW)
    assert (
        next(leg for leg in before["legs"] if leg["kind"] == "portal")["portal_id"]
        == "upper-portal"
    )
    req.closures = [
        lift_closure(None, type="path", floor_id="2", lat=42.391, lng=-72.528001, radius=1)
    ]
    after = plan_journey(outdoor, lambda _: engine, req, now=NOW)
    assert (
        next(leg for leg in after["legs"] if leg["kind"] == "portal")["portal_id"]
        == "demo-entrance-link"
    )
    assert after["legs"][-1]["uses_elevator"]
