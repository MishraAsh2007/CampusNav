"""Routing tests.

* toy-graph tests always run (no downloaded data needed)
* real-graph tests need data/graph.graphml and are skipped otherwise
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.graph.load import load_graph
from app.routing.pathfinding import plan_routes
from app.schemas import RouteRequest

A = {"lat": 42.3900, "lon": -72.5300}
B = {"lat": 42.3900, "lon": -72.5290}
MID_AB = {"lat": 42.3900, "lon": -72.5295}


def req(**kw):
    return RouteRequest.model_validate({"start": A, "end": B, **kw})


def kinds(result):
    return [s.kind for s in result.segments]


# ---------------------------------------------------------------- toy graph
def test_standard_takes_stairs_accessible_takes_elevator(toy_graph):
    r = plan_routes(toy_graph, req())
    assert kinds(r.standard) == ["steps"]
    assert r.standard.step_count == 12 and not r.standard.is_step_free
    assert kinds(r.accessible) == ["elevator"]
    assert r.accessible.is_step_free
    assert "elevator" in r.accessible.segments[0].instruction


def test_elevator_out_reroutes_accessible_only(toy_graph):
    closure = {"id": "e1", "type": "elevator_out", **MID_AB, "radius_m": 10}
    r = plan_routes(toy_graph, req(closures=[closure]))
    assert set(kinds(r.accessible)) == {"path"}        # detour A-C-D-B
    assert r.accessible.distance_m > 150
    assert kinds(r.standard) == ["steps"]              # stairs users unaffected
    assert r.accessible.closures_applied[0].id == "e1"


def test_standard_and_accessible_routes_differ_when_elevator_out(toy_graph):
    closure = {"id": "e1", "type": "elevator_out", **MID_AB, "radius_m": 10}
    r = plan_routes(toy_graph, req(closures=[closure]))
    assert r.accessible.geometry != r.standard.geometry


def test_no_accessible_route_when_detour_too_steep(steep_detour_graph):
    closure = {"id": "e1", "type": "elevator_out", **MID_AB, "radius_m": 10}
    r = plan_routes(steep_detour_graph, req(closures=[closure], max_grade_pct=5))
    assert not r.accessible.found and "step-free" in r.accessible.reason
    assert r.standard.found

    relaxed = plan_routes(steep_detour_graph, req(closures=[closure], max_grade_pct=10))
    assert relaxed.accessible.found  # user raised the grade limit


def test_construction_blocks_standard_too(toy_graph):
    closures = [{"id": "c", "type": "construction", **MID_AB, "radius_m": 10}]
    r = plan_routes(toy_graph, req(closures=closures))
    assert r.standard.found and set(kinds(r.standard)) == {"path"}
    assert r.accessible.found and set(kinds(r.accessible)) == {"path"}


def test_include_standard_false_skips_standard(toy_graph):
    assert plan_routes(toy_graph, req(include_standard=False)).standard is None


def test_astar_matches_dijkstra(toy_graph):
    from app.routing.pathfinding import find_path
    from app.routing.weights import Prefs

    p = Prefs("accessible", 5.0, True)
    assert find_path(toy_graph, 1, 2, p, algorithm="astar") == find_path(toy_graph, 1, 2, p, algorithm="dijkstra")


def test_response_is_json_serializable(toy_graph):
    json.loads(plan_routes(toy_graph, req()).model_dump_json())


# --------------------------------------------------------------- real graph
needs_graph = pytest.mark.skipif(not config.GRAPH_PATH.exists(), reason="run scripts/build_graph.py first")


def _mock(name):
    return json.loads((config.MOCKS_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_graph():
    return load_graph()


@needs_graph
def test_demo_points_standard_uses_stairs_accessible_goes_around(real_graph):
    r = plan_routes(real_graph, RouteRequest.model_validate(_mock("sample_request.json")))
    assert r.standard.found and r.accessible.found
    assert r.standard.steps_length_m > 0
    assert r.accessible.is_step_free and r.accessible.steps_length_m == 0
    assert r.accessible.geometry != r.standard.geometry          # the success metric
    assert r.accessible.distance_m > r.standard.distance_m       # the long way around
    assert r.meta.compute_ms < 500


@needs_graph
def test_mock_closures_reroute_accessible_and_expired_is_ignored(real_graph):
    body = _mock("sample_request.json")
    base = plan_routes(real_graph, RouteRequest.model_validate(body))
    body["closures"] = _mock("closures.json")
    r = plan_routes(real_graph, RouteRequest.model_validate(body))

    assert r.meta.closures_active == 1 and r.meta.closures_expired == 1
    assert r.accessible.closures_applied[0].edges_blocked > 0
    assert r.accessible.geometry != base.accessible.geometry
    assert r.accessible.distance_m > base.accessible.distance_m
    assert r.accessible.is_step_free
    assert r.standard.geometry == base.standard.geometry         # ramp closure doesn't affect stairs users


@needs_graph
def test_grade_limit_changes_accessible_route(real_graph):
    body = _mock("sample_request.json")
    strict = plan_routes(real_graph, RouteRequest.model_validate({**body, "max_grade_pct": 3}))
    relaxed = plan_routes(real_graph, RouteRequest.model_validate({**body, "max_grade_pct": 8}))
    if strict.accessible.found:
        assert strict.accessible.distance_m >= relaxed.accessible.distance_m


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@needs_graph
class TestApi:
    def test_health(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok" and body["nodes"] > 0

    def test_route_with_mock_files(self, client):
        body = _mock("sample_request.json")
        body["closures"] = _mock("closures.json")
        res = client.post("/route", json=body)
        assert res.status_code == 200
        data = res.json()
        assert data["accessible"]["found"] and data["standard"]["found"]
        assert data["accessible"]["geometry"]["geometry"]["type"] == "LineString"
        assert data["accessible"]["segments"][0]["instruction"]

    def test_invalid_grade_rejected(self, client):
        res = client.post("/route", json={**_mock("sample_request.json"), "max_grade_pct": 99})
        assert res.status_code == 422

    def test_far_away_point_rejected(self, client):
        body = {**_mock("sample_request.json"), "start": {"lat": 40.0, "lon": -73.0}}
        assert client.post("/route", json=body).status_code == 422
