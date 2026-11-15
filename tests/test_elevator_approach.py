from types import SimpleNamespace

from campus_routing.indoor import (
    IndoorEngine,
    IndoorRouteRequest,
    corridor_instruction,
)


def test_fixture_route_walks_to_lift_before_riding_then_walks_to_classroom(
    historical_ilc_mechanics,
):
    engine = IndoorEngine(historical_ilc_mechanics)
    route = engine.route(
        IndoorRouteRequest(
            building_id="ilc",
            start_node_id="ilc-entrance-south",
            end_node_id="ilc-source-n211-f2",
        )
    )
    ride_index = next(i for i, step in enumerate(route["steps"]) if step["kind"] == "elevator")
    assert ride_index >= 2  # The entrance and corridor approach cannot disappear.
    approach = route["steps"][ride_index - 1]
    assert approach["to_node_id"] == route["steps"][ride_index]["from_node_id"]
    assert "Elevator" in approach["instruction"] and "turn" in approach["instruction"]
    assert "Leave" in route["steps"][ride_index + 1]["instruction"]
    assert route["steps"][-1]["to_node_id"] == "ilc-source-n211-f2"
    assert route["directions"] == [step["instruction"] for step in route["steps"]]


def test_plan_turns_follow_route_direction_and_unknown_axes_do_not_invent_bearings():
    a = SimpleNamespace(label="Main corridor", kind="junction")
    b = SimpleNamespace(label="East elevator", kind="elevator_stop")
    floor = SimpleNamespace(label="Floor 1", coordinate_system="image_pixels")
    forward = corridor_instruction(a, b, floor, 10, [(0, 0), (10, 0)], [(0, -10), (0, 0)])
    assert "turn left" in forward
    reverse = corridor_instruction(a, b, floor, 10, [(0, 0), (0, -10)], [(10, 0), (0, 0)])
    assert "turn right" in reverse
    floor.coordinate_system = "local_meters"
    assert "turn" not in corridor_instruction(
        a, b, floor, 10, [(0, 0), (10, 0)], [(0, -10), (0, 0)]
    )


def test_walking_past_an_elevator_landing_does_not_tell_user_they_rode_it(historical_ilc_mechanics):
    engine = IndoorEngine(historical_ilc_mechanics)
    route = engine.route(
        IndoorRouteRequest(
            building_id="ilc",
            start_node_id="ilc-entrance-west",
            end_node_id="ilc-source-n111-f1",
        )
    )
    assert not route["uses_elevator"]
    assert all("Leave" not in step["instruction"] for step in route["steps"])
