from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pyproj import Geod

from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.models import Closure, Coordinate, RouteRequest
from scripts.make_demo import make_demo_graph

NOW = datetime(2026, 11, 13, 18, tzinfo=UTC)


@pytest.fixture
def engine():
    return RoutingEngine(make_demo_graph())


def request(**overrides):
    return RouteRequest.model_validate(
        {
            "start": {"lat": 42.391, "lng": -72.528},
            "end": {"lat": 42.392, "lng": -72.528},
            **overrides,
        }
    )


def closure(**overrides):
    return Closure.model_validate(
        {
            "lat": 42.391425,
            "lng": -72.5276,
            "radius": 8,
            "type": "elevator",
            "status": "closed",
            "source": "community",
            "start_time": NOW - timedelta(hours=1),
            "end_time": NOW + timedelta(hours=12),
            "last_confirmed": NOW,
            **overrides,
        }
    )


def test_demo_three_distinct_routes_and_no_state_leak(engine):
    normal = engine.route(request(no_stairs=False, max_grade=None), now=NOW)
    accessible = engine.route(request(), now=NOW)
    outage = engine.route(request(closures=[closure()]), now=NOW)
    assert normal.properties.uses_stairs
    assert not accessible.properties.uses_stairs
    assert accessible.properties.uses_elevator
    assert not outage.properties.uses_elevator
    assert not outage.properties.uses_stairs
    assert normal.properties.total_distance < accessible.properties.total_distance
    assert accessible.properties.total_distance < outage.properties.total_distance
    assert outage.properties.max_grade <= 5
    assert engine.route(request(), now=NOW) == accessible
    assert len({str(r.geometry.coordinates) for r in (normal, accessible, outage)}) == 3


@pytest.mark.parametrize(
    "change",
    [
        {"end_time": NOW},
        {"start_time": NOW + timedelta(seconds=1)},
    ],
)
def test_inactive_closures_do_not_change_route(engine, change):
    result = engine.route(request(closures=[closure(**change)]), now=NOW)
    assert result.properties.uses_elevator


def test_start_boundary_is_active_and_null_end_is_open(engine):
    result = engine.route(request(closures=[closure(start_time=NOW, end_time=None)]), now=NOW)
    assert not result.properties.uses_elevator


def test_degraded_area_penalized_but_still_traversable(engine):
    result = engine.route(request(closures=[closure(status="degraded")]), now=NOW)
    assert result.properties.uses_elevator
    assert any("degraded" in warning for warning in result.properties.warnings)


def test_grade_limit_applies_both_directions(engine):
    with pytest.raises(RoutingError, match="No route"):
        engine.route(request(max_grade=3, closures=[closure()]), now=NOW)
    with pytest.raises(RoutingError, match="No route"):
        engine.route(
            request(
                max_grade=3,
                closures=[closure()],
                start={"lat": 42.392, "lng": -72.528},
                end={"lat": 42.391, "lng": -72.528},
            ),
            now=NOW,
        )


def test_unknown_grades_are_not_flat():
    graph = make_demo_graph()
    for *_, edge in graph.edges(data=True):
        edge["grade_percent"] = None
    engine = RoutingEngine(graph)
    with pytest.raises(RoutingError):
        engine.route(request())
    result = engine.route(request(allow_unknown_grade=True))
    assert result.properties.max_grade is None
    assert any("unknown" in w for w in result.properties.warnings)


def test_unmatched_elevator_does_not_close_unrelated_path(engine):
    result = engine.route(request(closures=[closure(lat=42.3915, lng=-72.5288)]), now=NOW)
    assert result.properties.uses_elevator
    assert any("could not be matched" in w for w in result.properties.warnings)


def test_path_closure_intersects_middle_of_edge_in_meters(engine):
    result = engine.route(
        request(
            no_stairs=False,
            max_grade=None,
            closures=[
                closure(type="path", lat=42.3915, lng=-72.528, radius=5),
            ],
        ),
        now=NOW,
    )
    assert not result.properties.uses_stairs  # endpoints are ~55 m from the closure.
    assert result.properties.uses_elevator


def test_no_route_when_all_paths_closed(engine):
    with pytest.raises(RoutingError) as exc:
        engine.route(request(closures=[closure(type="path", radius=500)]), now=NOW)
    assert exc.value.code == "no_route"


def test_outside_coverage_rejected(engine):
    with pytest.raises(RoutingError) as exc:
        engine.route(request(start={"lat": 42, "lng": -72}))
    assert exc.value.code == "outside_coverage"


def test_geojson_order_and_reverse_geometry(engine):
    result = engine.route(
        request(
            no_stairs=False,
            max_grade=None,
            start={"lat": 42.392, "lng": -72.528},
            end={"lat": 42.391, "lng": -72.528},
        )
    )
    assert result.geometry.coordinates[0] == pytest.approx((-72.528, 42.392))
    assert result.geometry.coordinates[-1] == pytest.approx((-72.528, 42.391))


def test_start_and_end_inside_same_edge_do_not_travel_to_ends(engine):
    result = engine.route(
        request(
            no_stairs=False,
            max_grade=None,
            start={"lat": 42.39125, "lng": -72.528},
            end={"lat": 42.39175, "lng": -72.528},
        )
    )
    expected = Geod(ellps="WGS84").inv(-72.528, 42.39125, -72.528, 42.39175)[2]
    assert result.properties.total_distance == pytest.approx(expected, abs=0.02)
    assert result.geometry.coordinates[0] == pytest.approx((-72.528, 42.39125), abs=1e-7)
    assert result.geometry.coordinates[-1] == pytest.approx((-72.528, 42.39175), abs=1e-7)


def test_snap_does_not_jump_from_blocked_stairs_to_accessible_path(engine):
    with pytest.raises(RoutingError):
        engine.route(request(start={"lat": 42.3915, "lng": -72.528}))


def test_identical_endpoints_return_valid_zero_length_linestring(engine):
    point = {"lat": 42.3915, "lng": -72.528}
    result = engine.route(request(start=point, end=point))
    assert result.properties.total_distance == 0
    assert len(result.geometry.coordinates) == 2
    assert result.geometry.coordinates[0] == result.geometry.coordinates[1]


def test_parallel_edges_use_selected_edges_metrics_and_geometry():
    graph = make_demo_graph()
    edge = dict(graph[1][2][0])
    edge.update(kind="path", length=150, grade_percent=3, name="Parallel ramp")
    graph.add_edge(1, 2, key=1, **edge)
    result = RoutingEngine(graph).route(request())
    assert result.properties.total_distance == 150
    assert result.properties.max_grade == 3
    assert not result.properties.uses_stairs


def test_concurrent_requests_do_not_mutate_graph(engine):
    before = nx.node_link_data(engine.graph)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda i: engine.route(request(closures=[closure()] if i % 2 else []), now=NOW),
                range(12),
            )
        )
    assert [r.properties.uses_elevator for r in results] == [i % 2 == 0 for i in range(12)]
    assert nx.node_link_data(engine.graph) == before


@pytest.mark.parametrize(
    "data",
    [
        {"lat": 91, "lng": 0},
        {"lat": 0, "lng": float("nan")},
    ],
)
def test_invalid_coordinates(data):
    with pytest.raises(ValidationError):
        Coordinate.model_validate(data)


def test_timezone_and_interval_validation():
    with pytest.raises(ValidationError):
        closure(start_time="2026-11-13T12:00:00")
    with pytest.raises(ValidationError):
        closure(end_time=NOW - timedelta(days=1))


def test_api_contract_errors_and_cors(engine):
    with TestClient(create_app(engine)) as client:
        assert client.get("/health").json()["synthetic"] is True
        response = client.post("/route", json=request().model_dump(mode="json"))
        assert response.status_code == 200
        assert response.json()["type"] == "Feature"
        assert response.json()["geometry"]["type"] == "LineString"
        assert "total_distance" in response.json()["properties"]
        payload = request().model_dump(mode="json")
        payload["max_grade"] = -1
        assert client.post("/route", json=payload).status_code == 422
        payload = request(closures=[closure(type="path", radius=500, end_time=None)]).model_dump(
            mode="json"
        )
        assert client.post("/route", json=payload).status_code == 404
        assert (
            client.options(
                "/route",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            ).status_code
            == 200
        )


def test_missing_graph_is_503_without_silent_demo_fallback(tmp_path):
    with TestClient(create_app(graph_path=tmp_path / "missing.json")) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/route", json=request().model_dump(mode="json")).status_code == 503
