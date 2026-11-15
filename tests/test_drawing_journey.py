import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from campus_notices.cache import atomic_json
from campus_notices.plan_integrity import REVIEWED_HASHES
from campus_notices.plan_portals import NORTH_NODE, NORTH_POSITION, north_portal
from campus_notices.plan_portals import collect as collect_portals
from campus_routing.api import create_app
from campus_routing.drawing_journey import DrawingPortalRegistry
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.graph import save_graph
from campus_routing.indoor import IndoorEngine
from campus_routing.journey import JourneyRequest, plan_journey
from campus_routing.models import Closure
from scripts.build_additional_wayfinding import north_d, old_chapel
from scripts.demo_indoor import demo_map
from scripts.make_demo import make_demo_graph

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


def plan(building="north-d"):
    builder, floors = (north_d, "12345") if building == "north-d" else (old_chapel, "12")
    return builder(
        {f: dict(url="https://example.com/official-plan", sha256="a" * 64) for f in floors}
    )


def registry():
    return DrawingPortalRegistry.model_validate(
        dict(
            portals=[
                dict(
                    id="north-d-southwest",
                    building_id="north-d",
                    indoor_node_id="exit-threshold-1",
                    floor_id="1",
                    outdoor_node_id=1,
                    outdoor_approach_node_id=3,
                    position=dict(lat=42.391, lng=-72.528),
                    entrance_id="umass-entrance-50",
                    plan_source_sha256="a" * 64,
                    source_urls=["https://example.com/plan", "https://example.com/entrance"],
                    evidence="Synthetic journey portal fixture; not a real entrance.",
                    keycard_required=True,
                    step_free=True,
                    door_type="push-button",
                )
            ]
        )
    )


def request(**updates):
    return JourneyRequest.model_validate(
        dict(
            origin=dict(kind="drawing", building_id="north-d", node_id="apartment-513-5"),
            destination=dict(kind="outdoor", lat=42.392, lng=-72.528),
            accept_drawing_only=True,
            resident_access_confirmed=True,
        )
        | updates
    )


def run(req, *, portals=None, data=None, outdoor=None):
    return plan_journey(
        outdoor or RoutingEngine(make_demo_graph()),
        lambda _: IndoorEngine(demo_map(), allow_synthetic=True),
        req,
        now=NOW,
        get_drawing=lambda _: data or plan(),
        drawing_portals=portals or registry(),
    )


def closure(asset, **updates):
    return Closure(
        **(
            dict(
                lat=42.391,
                lng=-72.528,
                radius=1,
                type="elevator",
                status="closed",
                source="official",
                building_id="north-d",
                asset_id=asset,
                start_time=NOW - timedelta(hours=1),
                end_time=NOW + timedelta(hours=1),
                last_confirmed=NOW,
            )
            | updates
        )
    )


def test_combined_trip_and_return_use_exact_threshold_and_do_not_claim_indoor_meters():
    req = request()
    result = run(req)
    assert [leg["kind"] for leg in result["legs"]] == ["indoor", "portal", "outdoor"]
    inside, portal, outside = result["legs"]
    assert inside["steps"][-1]["to_node_id"] == "exit-threshold-1"
    assert [
        (s["from_floor"], s["to_floor"]) for s in inside["steps"] if s["kind"] == "elevator"
    ] == [("5", "1")]
    assert portal["geometry"] == dict(type="Point", coordinates=[-72.528, 42.391])
    assert portal["direction"] == "exit" and portal["entrance_id"] == "umass-entrance-50"
    assert outside["route"]["geometry"]["coordinates"][0] == pytest.approx([-72.528, 42.391])
    assert result["total_distance"] is None and inside["total_distance"] is None
    assert result["routing_cost"] is None and inside["routing_cost"] is None
    assert result["known_distance_m"] == outside["route"]["properties"]["total_distance"]
    assert result["distance_complete"] is False and result["physical_verification"] is False
    reverse = run(request(origin=req.destination.model_dump(), destination=req.origin.model_dump()))
    assert [leg["kind"] for leg in reverse["legs"]] == ["outdoor", "portal", "indoor"]
    assert reverse["legs"][1]["direction"] == "enter"
    assert reverse["legs"][-1]["steps"][-1]["to_node_id"] == "apartment-513-5"


def test_combines_drawing_and_existing_measured_indoor_engines():
    result = run(
        request(destination=dict(kind="indoor", building_id="demo-building", node_id="room-201"))
    )
    assert [leg["kind"] for leg in result["legs"]] == [
        "indoor",
        "portal",
        "outdoor",
        "portal",
        "indoor",
    ]
    assert result["legs"][-1]["building_id"] == "demo-building"
    assert result["legs"][-1]["total_distance"] > 0
    assert result["total_distance"] is None and result["synthetic"] is True


def test_two_drawing_buildings_compose_without_converting_plan_lengths_to_meters():
    portals = registry().model_dump(mode="json")
    second = dict(portals["portals"][0])
    second.update(
        id="synthetic-chapel-entry",
        building_id="old-chapel",
        indoor_node_id="entry-threshold-1",
        entrance_id="synthetic-entry",
        outdoor_node_id=2,
        outdoor_approach_node_id=6,
        position=dict(lat=42.392, lng=-72.528),
        keycard_required=False,
    )
    portals["portals"].append(second)
    req = request(
        destination=dict(kind="drawing", building_id="old-chapel", node_id="stage-ramp-approach-2")
    )
    result = plan_journey(
        RoutingEngine(make_demo_graph()),
        lambda _: None,
        req,
        now=NOW,
        get_drawing=plan,
        drawing_portals=DrawingPortalRegistry.model_validate(portals),
    )
    assert [leg["kind"] for leg in result["legs"]] == [
        "indoor",
        "portal",
        "outdoor",
        "portal",
        "indoor",
    ]
    assert all(leg["total_distance"] is None for leg in result["legs"] if leg["kind"] == "indoor")
    assert result["total_distance"] is None


@pytest.mark.parametrize(
    "update,code",
    [
        (dict(accept_drawing_only=False), "physical_verification_missing"),
        (dict(resident_access_confirmed=False), "resident_access_required"),
        (dict(min_width_m=1), "drawing_preferences_unsupported"),
        (dict(need_automatic_door=True), "drawing_preferences_unsupported"),
    ],
)
def test_consent_permissions_and_unenforceable_constraints_are_not_silently_relaxed(update, code):
    with pytest.raises(RoutingError) as error:
        run(request(**update))
    assert error.value.code == code


def test_bank_and_floor_specific_door_closures_block_journey_and_expired_reports_do_not():
    lift = closure("umass-elevator-148")
    door = closure("umass-entrance-50", type="path", floor_id="1")
    for c in [lift, door]:
        with pytest.raises(RoutingError) as error:
            run(request(closures=[c.model_dump(mode="json")]))
        assert error.value.code == "no_journey"
        expired = c.model_copy(update=dict(end_time=NOW))
        assert run(request(closures=[expired.model_dump(mode="json")]))["complete"]
    # An outage does not block unrelated same-floor shared circulation.
    result = run(
        request(
            origin=dict(kind="drawing", building_id="north-d", node_id="lobby-1"),
            destination=dict(kind="drawing", building_id="north-d", node_id="lounge-114-1"),
            closures=[lift.model_dump(mode="json")],
        )
    )
    assert len(result["legs"]) == 1 and result["legs"][0]["drawing_only"]


def test_missing_portal_never_snaps_a_different_building_to_nearby_outdoor_path():
    req = request(
        origin=dict(kind="drawing", building_id="old-chapel", node_id="stage-ramp-approach-2")
    )
    with pytest.raises(RoutingError) as error:
        run(req, data=plan("old-chapel"))
    assert error.value.code == "no_journey"
    same = request(
        origin=dict(kind="drawing", building_id="old-chapel", node_id="elevator-2"),
        destination=dict(kind="drawing", building_id="old-chapel", node_id="auditorium-2"),
    )
    assert run(same, data=plan("old-chapel"))["complete"]  # Indoor-only still works.


def test_changed_floor_source_and_moved_graph_anchor_reject_old_portals():
    changed = plan().model_copy(deep=True)
    changed.floor_sources["1"]["sha256"] = "b" * 64
    with pytest.raises(RoutingError) as error:
        run(request(), data=changed)
    assert error.value.code == "portal_source_mismatch"
    graph = make_demo_graph()
    graph.nodes[1]["lng"] += 0.001
    with pytest.raises(RoutingError) as error:
        run(request(), outdoor=RoutingEngine(graph))
    assert error.value.code == "invalid_portal"


def test_api_exposes_portal_evidence_and_new_journey_contract(tmp_path):
    folder = tmp_path / "maps"
    atomic_json(folder / "north-d.json", plan().model_dump(mode="json"))
    atomic_json(tmp_path / "plan_wayfinding_portals.json", registry().model_dump(mode="json"))
    with TestClient(
        create_app(engine=RoutingEngine(make_demo_graph()), plan_wayfinding_dir=folder)
    ) as client:
        response = client.get("/journey/portals")
        assert response.status_code == 200 and response.json()["portals"][0]["evidence"]
        result = client.post("/journey", json=request().model_dump(mode="json"))
        assert result.status_code == 200 and result.json()["total_distance"] is None
        # The existing indoor kind is not silently reinterpreted as a drawing.
        req = request().model_dump(mode="json")
        req["origin"]["kind"] = "indoor"
        assert client.post("/journey", json=req).status_code == 404


def source_fixture():
    graph = nx.MultiDiGraph(synthetic=True)
    graph.add_node(10, lng=NORTH_POSITION[0] - 0.00003, lat=NORTH_POSITION[1])
    graph.add_node(NORTH_NODE, lng=NORTH_POSITION[0], lat=NORTH_POSITION[1])
    for a, b in [(10, NORTH_NODE), (NORTH_NODE, 10)]:
        graph.add_edge(a, b, kind="path", length=3, grade_percent=1)
    gis = dict(
        entrances=[
            dict(
                attributes=dict(
                    OBJECTID=50, isAccessibleToAllFloors=1, IsKeyCardRequired=1, hasAutoDoorOpener=1
                ),
                geometry=dict(x=NORTH_POSITION[0], y=NORTH_POSITION[1]),
            )
        ]
    )
    xml = ET.fromstring(
        f'<osm><node id="{NORTH_NODE}" lon="{NORTH_POSITION[0]}" '
        f'lat="{NORTH_POSITION[1]}"/><way id="216955127">'
        f'<nd ref="{NORTH_NODE}"/></way><way id="217134889">'
        f'<nd ref="10"/><nd ref="{NORTH_NODE}"/>'
        '<tag k="highway" v="footway"/></way></osm>'
    )
    data = plan()
    data.floor_sources["1"]["sha256"] = REVIEWED_HASHES["673-01.pdf"]
    return gis, xml, RoutingEngine(graph), data


def test_source_join_requires_building_outline_and_footway_identity_not_just_proximity():
    gis, xml, outdoor, data = source_fixture()
    portal = north_portal(gis, xml, outdoor, data)
    assert portal.outdoor_node_id == NORTH_NODE
    assert portal.geometry[0] == portal.geometry[-1] == NORTH_POSITION
    xml.find("way/nd").set("ref", "999")
    with pytest.raises(ValueError, match="building and footway"):
        north_portal(gis, xml, outdoor, data)


def test_source_join_rejects_new_steps_and_retracted_official_accessibility():
    gis, xml, outdoor, data = source_fixture()
    graph = outdoor.graph.copy()
    graph[10][NORTH_NODE][0]["kind"] = "steps"
    with pytest.raises(ValueError, match="steps"):
        north_portal(gis, xml, RoutingEngine(graph), data)
    gis["entrances"][0]["attributes"]["isAccessibleToAllFloors"] = 0
    with pytest.raises(ValueError, match="no longer"):
        north_portal(gis, xml, outdoor, data)


def test_collector_revalidation_removes_old_portal_when_source_retracts_access(tmp_path):
    gis, xml, outdoor, data = source_fixture()
    gis_path = tmp_path / ".cache/residence-access.json"
    atomic_json(gis_path, gis)
    ET.ElementTree(xml).write(tmp_path / ".cache/residence-map.osm")
    atomic_json(
        tmp_path / "data/private/plan_wayfinding/north-d.json", data.model_dump(mode="json")
    )
    save_graph(outdoor.graph, tmp_path / "data/umass-residences.graph.json")
    assert len(collect_portals(tmp_path).portals) == 1
    gis["entrances"][0]["attributes"]["isAccessibleToAllFloors"] = 0
    atomic_json(gis_path, gis)
    result = collect_portals(tmp_path)
    assert not result.portals
    assert any(row["building_id"] == "north-d" for row in result.unresolved)
