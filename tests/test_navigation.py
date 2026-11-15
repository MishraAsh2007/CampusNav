from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from campus_notices.cache import atomic_json
from campus_notices.indoor_sources import create_indoor_drafts, parse_source, refresh_indoor_sources
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine
from campus_routing.indoor import IndoorEngine, IndoorMap, IndoorRouteRequest
from campus_routing.navigation import ArrivalRequest, NavigationRequest, NavigationService
from campus_routing.places import LocationQuery, PlaceResolver
from scripts.demo_indoor import NOW
from scripts.demo_navigation import pilot_fixtures, pilot_outage
from scripts.enable_pilot_rooms import PILOTS
from scripts.make_demo import make_demo_graph


def service(closures=None):
    return NavigationService(
        RoutingEngine(make_demo_graph()),
        PlaceResolver(pilot_fixtures(), {}, allow_synthetic=True),
        lambda: (closures or [], dict(stale=False)),
    )


def trip(**updates):
    return NavigationRequest.model_validate(
        dict(
            origin=dict(building_id="library", floor_id="2", node_id="a2"),
            destination=dict(text="ILC"),
            **updates,
        )
    )


def arrival(**updates):
    return ArrivalRequest.model_validate(
        dict(
            building_id="ilc",
            portal_id="ilc-entrance",
            confirmed=True,
            continue_indoors=True,
            destination=dict(text="N211"),
            **updates,
        )
    )


def lifts(response):
    return [
        t["asset_id"]
        for leg in response["journey"]["legs"]
        if leg["kind"] == "indoor"
        for t in leg["transitions"]
    ]


def test_floor_alone_needs_a_landmark_not_an_assumed_elevator():
    nav = service()
    assert nav.plan(NavigationRequest(), now=NOW)["code"] == "choose_building"
    response = nav.resolver.resolve(LocationQuery(text="second floor of the library"))
    assert response["code"] == "choose_landmark"
    assert response["location"]["floor_id"] == "2"
    assert response["choices"] and all(c["floor_id"] == "2" for c in response["choices"])
    assert "endpoint" not in response


def test_coverage_reports_building_routes_without_claiming_room_routes():
    resolver = service().resolver
    coverage = resolver.coverage("library")
    assert coverage["routable"] is True
    assert coverage["room_routable"] is True
    assert coverage["room_nodes"] == 1

    data = pilot_fixtures()["library"].model_dump(mode="json")
    data["nodes"] = [node for node in data["nodes"] if node["kind"] != "room"]
    node_ids = {node["id"] for node in data["nodes"]}
    data["edges"] = [
        edge
        for edge in data["edges"]
        if edge["start"] in node_ids and edge["end"] in node_ids
    ]
    data["maneuvers"] = [
        cue
        for cue in data["maneuvers"]
        if cue["from_node"] in node_ids
        and cue["via_node"] in node_ids
        and cue["to_node"] in node_ids
    ]
    resolver = PlaceResolver(
        {"library": IndoorMap.model_validate(data), "ilc": pilot_fixtures()["ilc"]},
        {},
        allow_synthetic=True,
    )
    coverage = resolver.coverage("library")
    assert coverage["routable"] is True
    assert coverage["room_routable"] is False
    assert coverage["room_nodes"] == 0


def test_pilot_room_contracts_are_source_linked():
    assert set(PILOTS) == {"library", "ilc"}
    for pilot in PILOTS.values():
        assert pilot["node"]["source_record_ids"]
        assert "field-verified" in pilot["note"]


def test_resolve_aliases_conflicts_and_unknown_floors():
    resolver = service().resolver
    result = resolver.resolve(LocationQuery(text="ILC room N 211"), purpose="destination")
    assert result["endpoint"]["node_id"] == "room-201"
    assert result["floor_id"] == "2"
    assert (
        resolver.resolve(LocationQuery(text="elevator A in the library"))["code"]
        == "ambiguous_landmark"
    )
    assert resolver.resolve(LocationQuery(text="library floor 99"))["code"] == "choose_floor"
    assert (
        resolver.resolve(LocationQuery(text="ILC", building_id="library"))["code"]
        == "choose_building"
    )
    assert (
        resolver.resolve(LocationQuery(text="Science and Engineering Library"))["code"]
        == "choose_building"
    )
    assert (
        resolver.resolve(LocationQuery(text="library mystery room"), allow_building=True)["status"]
        == "needs_input"
    )


def test_floor_and_node_cannot_contradict_each_other():
    result = service().resolver.resolve(
        LocationQuery(building_id="library", floor_id="1", node_id="a2")
    )
    assert result["status"] == "needs_input"


def test_complete_departure_outdoor_arrival_and_indoor_continuation():
    nav = service()
    result = nav.plan(trip(), now=NOW)
    assert result["status"] == "route_ready"
    assert result["journey"]["synthetic"] is True
    assert lifts(result) == ["library-lift-a"]
    assert [s["phase"] for s in result["stages"]] == ["leave_building", "leave_building", "outdoor"]
    assert result["arrival_context"] == dict(building_id="ilc", portal_id="ilc-entrance")
    prompt = nav.arrive(ArrivalRequest(**result["arrival_context"]), now=NOW)
    assert prompt["code"] == "confirm_arrival"
    prompt = nav.arrive(ArrivalRequest(**result["arrival_context"], confirmed=True), now=NOW)
    assert prompt["field"] == "continue_indoors"
    finished = nav.arrive(
        ArrivalRequest(**result["arrival_context"], confirmed=True, continue_indoors=False), now=NOW
    )
    assert finished["status"] == "arrived" and finished["scope"] == "outside_entrance_approach"
    indoor = nav.arrive(arrival(), now=NOW)
    assert indoor["status"] == "route_ready"
    assert lifts(indoor) == ["ilc-lift-a"]
    assert any(s["phase"] == "enter_building" for s in indoor["stages"])
    assert any("second classroom" in line for s in indoor["stages"] for line in s["instructions"])


def test_fresh_closures_are_read_again_at_arrival_and_preferences_do_not_relax():
    closures = []
    nav = service(closures)
    assert nav.plan(trip(), now=NOW)["status"] == "route_ready"
    closures.append(pilot_outage())
    after = nav.arrive(arrival(), now=NOW)
    assert lifts(after) == ["ilc-lift-b"]
    assert not any(
        "second classroom" in line for s in after["stages"] for line in s["instructions"]
    )
    closures.append(pilot_outage(lift="b"))
    assert nav.arrive(arrival(), now=NOW)["status"] == "no_route"
    assert lifts(nav.arrive(arrival(closures=[]), now=NOW)) == ["ilc-lift-a"]


def test_closed_entrance_blocks_arrival_route_without_affecting_other_floors():
    closure = pilot_outage().model_copy(
        update=dict(
            type="path",
            asset_id="ilc-approach",
            floor_id="1",
            radius=7,
        )
    )
    closures = [closure]
    nav = service(closures)
    data = nav.resolver.maps["ilc"].model_dump(mode="json")
    data["assets"].append(
        dict(
            id="ilc-approach",
            label="Synthetic entrance approach",
            kind="path",
            source_id=data["sources"][0]["id"],
        )
    )
    data["portals"][0]["asset_id"] = "ilc-approach"
    nav.resolver.maps["ilc"] = IndoorMap.model_validate(data)
    assert nav.arrive(arrival(), now=NOW)["status"] == "no_route"
    closures[0] = closure.model_copy(update={"floor_id": "2"})
    assert nav.arrive(arrival(), now=NOW)["status"] == "route_ready"


def test_full_room_to_room_journey_without_waiting_for_arrival_prompt():
    req = trip().model_copy(update={"destination": LocationQuery(text="ILC N211")})
    result = service().plan(req, now=NOW)
    assert lifts(result) == ["library-lift-a", "ilc-lift-a"]


def test_directional_cues_are_validated_and_do_not_reverse_automatically():
    data = pilot_fixtures()["ilc"]
    engine = IndoorEngine(data, allow_synthetic=True)
    route = engine.route(
        IndoorRouteRequest(building_id="ilc", start_node_id="room-201", end_node_id="entrance"),
        now=NOW,
    )
    assert all("second classroom" not in line for line in route["directions"])
    raw = data.model_dump(mode="json")
    raw["maneuvers"][0]["from_node"] = "entrance"
    with pytest.raises(ValidationError, match="connected directed edges"):
        IndoorMap.model_validate(raw)


ILC_HTML = """<table><tr><th>Room</th><th>Capacity</th>
<th>Type of Room</th><th>Room Details</th></tr>
<tr><td>N211</td><td>52</td><td>Flex</td><td>Movable seating</td></tr>
<tr><td>N151</td><td>340</td><td>Auditorium</td>
<td>entryway from 1st and 2nd floors</td></tr></table>"""


def test_ilc_scraper_preserves_room_identity_without_guessing_floor_or_doors(tmp_path):
    records = parse_source("ilc-classrooms", ILC_HTML, NOW)
    assert records[0]["floor_label"] is None and records[0]["floor_labels"] == []
    assert records[1]["floor_labels"] == ["1", "2"]
    assert all(not r["routing_eligible"] for r in records)
    create_indoor_drafts(dict(records=records), tmp_path)
    draft = IndoorMap.model_validate_json((tmp_path / "ilc.json").read_text())
    assert not draft.nodes and draft.status == "draft"
    resolver = PlaceResolver({"ilc": draft}, dict(records=records))
    result = resolver.resolve(LocationQuery(text="ILC N211"), purpose="destination")
    assert result["status"] == "coverage_unavailable" and "endpoint" not in result
    assert "floor_id" not in result["location"]


def test_ilc_scrape_failure_preserves_source_observation(tmp_path):
    records = parse_source("ilc-classrooms", ILC_HTML, NOW)
    path = tmp_path / "sources.json"
    atomic_json(
        path, dict(records=records, sources={"ilc-classrooms": dict(observed_at=NOW.isoformat())})
    )
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        result = refresh_indoor_sources(path, client=client, now=datetime.now(UTC))
    assert result["sources"]["ilc-classrooms"]["mode"] == "cache"
    assert result["records"] == records


def test_navigation_api_scope_and_default_snapshot_contract(tmp_path):
    for key, data in pilot_fixtures().items():
        raw = data.model_dump(mode="json")
        raw["synthetic"] = False  # Isolated TestClient inputs, never written to data/indoor.
        atomic_json(tmp_path / (key + ".json"), raw)
    with TestClient(
        create_app(
            engine=RoutingEngine(make_demo_graph()),
            indoor_dir=tmp_path,
            official_path=tmp_path / "missing-snapshot.json",
        )
    ) as client:
        assert {b["id"] for b in client.get("/navigation/catalog").json()["buildings"]} == {
            "library",
            "ilc",
        }
        assert client.post("/navigation/plan", json={}).json()["status"] == "needs_input"
        payload = trip().model_dump(mode="json")
        assert client.post("/navigation/plan", json=payload).status_code == 503
        payload["closures"] = []
        result = client.post("/navigation/plan", json=payload)
        assert result.status_code == 200 and result.json()["status"] == "route_ready"
        assert result.json()["closure_context"]["mode"] == "request"
        assert (
            client.post(
                "/navigation/resolve", json={"location": {"building_id": "../private"}}
            ).status_code
            == 422
        )
