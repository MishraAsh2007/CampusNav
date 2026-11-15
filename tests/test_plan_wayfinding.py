from datetime import UTC, datetime, timedelta

import pytest

from campus_routing.engine import RoutingError
from campus_routing.models import Closure
from campus_routing.plan_wayfinding import PlanWayfindingRequest, plan_directions
from scripts.trace_brett_wayfinding import build


def request(**updates):
    return PlanWayfindingRequest(
        **(
            dict(
                start_node_id="room-101",
                end_node_id="room-111",
                accept_drawing_only=True,
                resident_access_confirmed=True,
            )
            | updates
        )
    )


def test_same_floor_room_to_room_directions_do_not_invent_access_or_distance():
    data = build("https://example.com/plan.pdf", "a" * 64)
    result = plan_directions(data, request())
    assert result["physical_verification"] is False and result["distance_m"] is None
    assert result["max_grade"] is None
    assert result["steps"][0]["kind"] == "door" and result["steps"][-1]["kind"] == "door"
    assert result["steps"][-1]["to_node_id"] == "room-111"
    reverse = plan_directions(data, request(start_node_id="room-111", end_node_id="room-101"))
    assert reverse["steps"][-1]["to_node_id"] == "room-101"


def test_explicit_drawing_limit_and_resident_permission_are_required():
    data = build("https://example.com/plan.pdf", "a" * 64)
    with pytest.raises(RoutingError, match="Verified accessible navigation is unavailable"):
        plan_directions(data, request(accept_drawing_only=False))
    with pytest.raises(RoutingError, match="permitted"):
        plan_directions(data, request(resident_access_confirmed=False))


def test_exact_door_outage_blocks_path_but_other_buildings_and_expired_reports_do_not():
    data = build("https://example.com/plan.pdf", "a" * 64)
    now = datetime.now(UTC)
    c = Closure(
        lat=0,
        lng=0,
        radius=1,
        type="path",
        status="closed",
        source="official",
        building_id="brett",
        floor_id="1",
        asset_id="brett-door-111",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        last_confirmed=now,
    )
    with pytest.raises(RoutingError, match="No drawing connection"):
        plan_directions(data, request(closures=[c]), now=now)
    for update in [dict(building_id="brown-house"), dict(floor_id="2"), dict(end_time=now)]:
        assert plan_directions(data, request(closures=[c.model_copy(update=update)]), now=now)[
            "steps"
        ]


def test_unknown_node_is_rejected_without_floor_guessing():
    data = build("https://example.com/plan.pdf", "a" * 64)
    with pytest.raises(RoutingError, match="Choose a destination"):
        plan_directions(data, request(end_node_id="room-201"))
