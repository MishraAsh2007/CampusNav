"""Entrance choice, closure lifecycle, and the frontend-facing API contract."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from campus_notices.cache import atomic_json
from campus_notices.community import ReportStore, UserReport
from campus_routing.api import create_app
from campus_routing.buildings import Place, TripRequest, choices, plan_trip
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.models import Closure, Coordinate, RouteRequest
from scripts.make_demo import make_demo_graph

NOW = datetime(2026, 11, 14, 5, tzinfo=UTC)


@pytest.fixture
def engine():
    return RoutingEngine(make_demo_graph())


def coord(engine, node):
    return Coordinate(**engine.graph.nodes[node])


def catalog(engine):
    return {
        "buildings": [
            {
                "id": "start",
                "name": "Start building",
                "in_routing_area": True,
                "entrances": [
                    dict(
                        id="start-door",
                        name="West door",
                        **coord(engine, 1).model_dump(),
                        step_free=None,
                        door_type="unknown",
                        keycard_required=False,
                    )
                ],
                "elevators": {"list": []},
            },
            {
                "id": "end",
                "name": "End building",
                "in_routing_area": True,
                "entrances": [
                    dict(
                        id="end-door",
                        name="East door",
                        **coord(engine, 2).model_dump(),
                        step_free=True,
                        door_type="automatic",
                        keycard_required=False,
                    )
                ],
                "elevators": {"list": []},
            },
        ]
    }


def outage(**overrides):
    return Closure(
        lat=42.391425,
        lng=-72.5276,
        radius=8,
        type="elevator",
        status="closed",
        source="community",
        start_time=NOW - timedelta(hours=1),
        end_time=NOW + timedelta(hours=24),
        last_confirmed=NOW,
        **overrides,
    )


def test_multi_entrance_search_matches_all_pairs(engine):
    starts = [coord(engine, n) for n in (1, 7)]
    ends = [coord(engine, n) for n in (2, 6)]
    for closures in ([], [outage()]):
        request = RouteRequest(start=starts[0], end=ends[0], closures=closures)
        expected = []
        for si, start in enumerate(starts):
            for ei, end in enumerate(ends):
                route = engine.route(
                    request.model_copy(update={"start": start, "end": end}), now=NOW
                )
                expected.append((route.properties.routing_cost, si, ei))
        result, si, ei = engine.route_many(request, starts, ends, now=NOW)
        assert (result.properties.routing_cost, si, ei) == min(expected)


def test_multi_entrance_skips_blocked_option_without_snapping_across_closure(engine):
    starts = [coord(engine, 4), coord(engine, 7)]
    end = coord(engine, 6)
    request = RouteRequest(start=starts[0], end=end)
    _, si, _ = engine.route_many(request, starts, [end], now=NOW)
    assert si == 0
    _, si, _ = engine.route_many(
        request.model_copy(update={"closures": [outage()]}), starts, [end], now=NOW
    )
    assert si == 1


def test_plan_keeps_constraints_and_flags_unknown_door_access(engine):
    data = catalog(engine)
    request = TripRequest(
        origin=Place(**coord(engine, 1).model_dump(), building_id="start"),
        destination=Place(**coord(engine, 2).model_dump(), building_id="end"),
    )
    result = plan_trip(engine, data, request, now=NOW)
    assert result["standard"].properties.uses_stairs
    assert not result["accessible"].properties.uses_stairs
    assert any("unverified" in note for note in result["notes"])
    strict = plan_trip(engine, data, request.model_copy(update={"need_automatic_door": True}))
    assert strict["accessible"] is None
    assert "No mapped public entrance" in strict["failure"]
    assert strict["standard"] is not None


def test_no_centroid_fallback_or_entrance_id_in_another_building(engine):
    data = catalog(engine)
    place = Place(**coord(engine, 1).model_dump(), building_id="start", entrance_id="end-door")
    with pytest.raises(RoutingError, match="does not belong"):
        choices(place, data, step_free=True, automatic=False)
    place.entrance_id = None
    data["buildings"][0]["entrances"][0]["keycard_required"] = True
    with pytest.raises(RoutingError, match="No mapped public entrance"):
        choices(place, data, step_free=True, automatic=False)


def test_community_persistence_expiry_confirmation_and_restoration(tmp_path):
    path = tmp_path / "community.json"
    store = ReportStore(path)
    report = UserReport(lat=42.39, lng=-72.528, type="path", status="broken", timestamp=NOW)
    saved = store.submit(report, now=NOW)
    assert len(ReportStore(path).active(NOW)) == 1
    later = NOW + timedelta(hours=23)
    store.confirm(saved["id"], now=later)
    assert len(store.active(NOW + timedelta(hours=25))) == 1
    assert not store.active(NOW + timedelta(hours=48))
    store.submit(report.model_copy(update={"timestamp": later, "status": "working"}), now=later)
    assert not store.active(later)
    with pytest.raises(ValueError, match="future"):
        store.submit(report.model_copy(update={"timestamp": NOW + timedelta(hours=2)}), now=NOW)


def test_api_keeps_scheduled_and_official_notices_separate_from_student_resolutions(
    engine, tmp_path
):
    now = datetime.now(UTC)
    official = tmp_path / "official.json"
    buildings = tmp_path / "buildings.json"
    atomic_json(buildings, catalog(engine))
    base = outage().model_dump(mode="json")
    base.update(
        notice_id="notice",
        location_id="test-lift",
        source_id="umass",
        source_ref="https://example.org/notice",
        parser="rules",
        source="official",
        start_time=(now - timedelta(hours=1)).isoformat(),
        end_time=(now + timedelta(hours=2)).isoformat(),
        last_confirmed=now.isoformat(),
    )
    future = dict(base, id="future", start_time=(now + timedelta(hours=1)).isoformat())
    atomic_json(
        official,
        dict(
            generated_at=now.isoformat(),
            closures=[dict(base, id="active"), future],
            counts={},
            sources=["umass"],
            source_observed_at={"umass": now.isoformat()},
        ),
    )
    with TestClient(
        create_app(
            engine=engine,
            official_path=official,
            buildings_path=buildings,
            community_path=tmp_path / "reports.json",
        )
    ) as client:
        assert [c["id"] for c in client.get("/closures").json()] == ["active"]
        assert len(client.get("/notices").json()) == 2
        report = dict(
            lat=base["lat"],
            lng=base["lng"],
            type="elevator",
            status="broken",
            timestamp=now.isoformat(),
        )
        saved = client.post("/reports", json=report)
        assert saved.status_code == 201
        assert client.post(f"/reports/{saved.json()['id']}/confirm").status_code == 200
        assert len(client.get("/closures").json()) == 2
        assert client.post("/reports", json=dict(report, status="working")).status_code == 201
        assert [c["id"] for c in client.get("/closures").json()] == ["active"]
        assert client.post("/reports", json=dict(report, connector_id="made-up")).status_code == 422
        body = {
            "origin": dict(coord(engine, 1).model_dump(), building_id="start"),
            "destination": dict(coord(engine, 2).model_dump(), building_id="end"),
        }
        planned = client.post("/plan", json=body)
        assert planned.status_code == 200
        assert planned.json()["accessible"]["geometry"]["type"] == "LineString"


def test_multi_entrance_zero_length_uses_same_anchor(engine):
    point = Coordinate(lat=42.3912, lng=-72.5276)
    req = RouteRequest(start=point, end=point)
    result, si, ei = engine.route_many(req, [point], [point], now=NOW)
    assert result.properties.total_distance == 0
    assert si == ei == 0


def test_corrupt_store_does_not_silently_claim_no_outages(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        ReportStore(path).active(NOW)
