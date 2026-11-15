import json

import httpx
import networkx as nx
import pytest

from campus_routing.elevation import fetch_elevations
from campus_routing.graph import load_graph, save_graph
from scripts.build_graph import incline_percent, normalize
from scripts.make_demo import make_demo_graph


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("-5%", 5),
        ("5", 5),
        ("0%", 0),
        ("45°", 100),
        ("up", None),
        ("nan", None),
    ],
)
def test_osm_incline_units(value, expected):
    if expected is None:
        assert incline_percent(value) is None
    else:
        assert incline_percent(value) == pytest.approx(expected)


def test_steps_with_ramp_tag_still_blocked_and_grade_uses_absolute_rise():
    osm = nx.MultiDiGraph()
    osm.add_node(1, x=-72.528, y=42.391)
    osm.add_node(2, x=-72.528, y=42.392)
    osm.add_edge(1, 2, length=100, highway="steps", ramp="yes")
    osm.add_edge(2, 1, length=100, highway="steps", ramp="yes")
    graph = normalize(osm, {(42.391, -72.528): 100, (42.392, -72.528): 90}, bbox=[])
    assert graph[1][2][0]["kind"] == "steps"
    assert graph[1][2][0]["grade_percent"] == 10
    assert graph[2][1][0]["grade_percent"] == 10


def test_graph_roundtrip_preserves_parallel_edges(tmp_path):
    graph = make_demo_graph()
    graph.add_edge(1, 2, **graph[1][2][0])
    path = tmp_path / "graph.json"
    save_graph(graph, path)
    assert nx.node_link_data(load_graph(path)) == nx.node_link_data(graph)


def test_elevation_cache_and_missing_samples(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {"elevation": 100},
                    {"elevation": None},
                ],
            },
        )

    path = tmp_path / "cache.json"
    points = [(42.391, -72.528), (42.392, -72.528)]
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = fetch_elevations(points, path, client=client, pause=0)
        assert result[points[0]] == 100
        assert result[points[1]] is None
        assert fetch_elevations([points[0]], path, client=client)[points[0]] == 100
    assert len(calls) == 1


def test_bad_elevation_response_does_not_overwrite_cache(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"other-provider": {"point": 12}}))
    original = path.read_bytes()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"status": "OK", "results": []})
        )
    ) as client:
        with pytest.raises(ValueError, match="Unexpected"):
            fetch_elevations([(42.391, -72.528)], path, client=client)
    assert path.read_bytes() == original
