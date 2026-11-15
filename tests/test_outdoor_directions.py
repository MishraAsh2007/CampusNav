import math
from itertools import pairwise
from pathlib import Path

import pytest
from shapely.geometry import LineString

from campus_routing.buildings import TripRequest, plan_trip, read_buildings
from campus_routing.directions import walking_directions
from campus_routing.engine import RoutingEngine


def edge(points, **changes):
    return {
        "line": LineString(points),
        "length": sum(math.dist(a, b) for a, b in pairwise(points)),
        "kind": "path",
        "grade_percent": 2,
        **changes,
    }


def directions(edges):
    return walking_directions(edges, lambda x, y: (x, y), tuple(edges[-1]["line"].coords[-1]))


@pytest.mark.parametrize("split", [False, True])
def test_same_unnamed_path_keeps_left_and_right_turns_inside_and_between_edges(split):
    points = [(0, 0), (20, 0), (20, 15), (35, 15), (35, 25)]
    edges = [edge([a, b]) for a, b in pairwise(points)] if split else [edge(points)]
    steps = directions(edges)
    assert [s["maneuver"] for s in steps] == ["depart", "left", "right", "left", "arrive"]
    assert [s["at"] for s in steps] == points
    assert [s["distance_m"] for s in steps] == [20, 15, 15, 10, 0]
    assert "Turn left" in steps[1]["instruction"]
    assert "Turn right" in steps[2]["instruction"]


def test_reversing_the_route_reverses_the_turn_directions():
    points = [(35, 25), (35, 15), (20, 15), (20, 0), (0, 0)]
    assert [s["maneuver"] for s in directions([edge(points)])] == [
        "depart",
        "right",
        "left",
        "right",
        "arrive",
    ]


def test_collinear_nodes_and_tiny_cartographic_zigzags_do_not_become_spoken_turns():
    points = [(0, 0), (5, 0), (10, 0), (10, 0.1), (20, 0), (25, 0)]
    assert len(directions([edge(points)])) == 2


def test_metric_distance_uses_edge_lengths_and_preserves_unknown_grades():
    steps = directions([edge([(0, 0), (10, 0), (10, 10)], length=60, grade_percent=None)])
    assert sum(s["distance_m"] for s in steps) == 60
    assert all(s["grade_pct"] is None for s in steps)


def test_stairs_and_elevator_transitions_are_explicit():
    steps = directions(
        [
            edge([(0, 0), (10, 0)]),
            edge([(10, 0), (20, 0)], kind="steps"),
            edge([(20, 0), (21, 0)], kind="elevator"),
        ]
    )
    assert [s["maneuver"] for s in steps] == ["depart", "stairs", "elevator", "arrive"]


def test_same_location_has_only_arrival():
    assert walking_directions([], lambda x, y: (x, y), (-72.5, 42.3))[0]["maneuver"] == "arrive"


def test_real_campus_route_has_located_turns_and_compatible_string_directions():
    root = Path(__file__).resolve().parents[1]
    engine = RoutingEngine.from_file(root / "data/umass-residences.graph.json")
    result = plan_trip(
        engine,
        read_buildings(root / "data/residence_buildings.json"),
        TripRequest.model_validate(
            {
                "origin": {"lat": 42.3911, "lng": -72.5276, "building_id": "campus-center"},
                "destination": {"lat": 42.3897, "lng": -72.5282, "building_id": "library"},
                "max_grade": 5,
            }
        ),
    )
    route = result["accessible"]
    assert route is not None
    p = route.properties
    assert len(p.maneuvers) > 2
    assert any(
        m.maneuver in ("left", "right", "slight-left", "slight-right", "sharp-left", "sharp-right")
        for m in p.maneuvers
    )
    assert p.directions == [m.instruction for m in p.maneuvers]
    assert sum(m.distance_m for m in p.maneuvers) == pytest.approx(p.total_distance, abs=0.1)
    assert all(m.at in route.geometry.coordinates for m in p.maneuvers)
