import networkx as nx
import pytest

from campus_notices.cache import atomic_json
from campus_routing.engine import RoutingError
from campus_routing.indoor import IndoorEngine
from scripts.import_indoor import import_map
from scripts.trace_brown_pilot import build

SOURCE = dict(
    id="source-plan",
    url="https://example.com/426-01.pdf",
    edition="Isolated contract fixture",
    observed_at="2026-11-14T12:00:00Z",
)


def test_brown_trace_requires_suite_and_lobby_doors_in_both_directions():
    data, review = build(SOURCE)
    graph = nx.Graph((edge.start, edge.end) for edge in data.edges)
    path = review["traced_path"]
    assert "suite-107-door" in path and "lobby-door" in path
    assert nx.shortest_path(graph, path[-1], path[0]) == list(reversed(path))
    assert not graph.has_edge("room-107d-threshold", "hall-suite-107")
    graph.remove_node("suite-107-door")
    assert not nx.has_path(graph, path[0], path[-1])


def test_unverified_geometry_cannot_serve_or_publish_navigation(tmp_path):
    data, review = build(SOURCE)
    assert data.status == "draft" and not data.portals
    assert not any(e.kind == "elevator" for e in data.edges)
    assert all(e.step_free is None and e.grade_percent is None for e in data.edges)
    assert all(not e.public_access for e in data.edges)
    assert review["routing_eligible"] is False and review["scale_spread_percent"] > 8
    with pytest.raises(RoutingError, match="awaiting review"):
        IndoorEngine(data)
    source = tmp_path / "map.json"
    atomic_json(source, data.model_dump(mode="json"))
    with pytest.raises(ValueError, match="reviewed, non-synthetic"):
        import_map(source, tmp_path / "production", tmp_path / "outdoor.json")


def test_all_trace_segments_stay_in_source_drawing_bounds():
    data, _ = build(SOURCE)
    for edge in data.edges:
        assert edge.length_m > 0
        for x, y in edge.geometry:
            assert 0 <= x <= 792 and 0 <= y <= 612
