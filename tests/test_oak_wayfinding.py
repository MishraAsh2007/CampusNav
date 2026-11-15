from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from campus_notices.cache import atomic_json
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.models import Closure
from campus_routing.plan_wayfinding import PlanWayfindingMap, PlanWayfindingRequest, plan_directions
from scripts.make_demo import make_demo_graph
from scripts.trace_oak_wayfinding import BANK, build


def data():
    return build({f: dict(url=f"https://example.com/{f}.pdf", sha256=f * 64) for f in ["1", "2"]})


def request(**updates):
    return PlanWayfindingRequest(
        **(
            dict(
                start_node_id="outside-233",
                end_node_id="exit-threshold",
                accept_drawing_only=True,
                resident_access_confirmed=True,
            )
            | updates
        )
    )


def closure(floor=None):
    now = datetime.now(UTC)
    return Closure(
        lat=0,
        lng=0,
        radius=1,
        type="elevator",
        status="closed",
        source="official",
        asset_id=BANK,
        building_id="oak",
        floor_id=floor,
        start_time=now - timedelta(minutes=1),
        end_time=now + timedelta(hours=1),
        last_confirmed=now,
    )


def test_shared_hall_to_exit_and_reverse_use_separate_floor_landings():
    result = plan_directions(data(), request())
    transition = next(s for s in result["steps"] if s["kind"] == "elevator")
    assert (transition["from_floor"], transition["to_floor"]) == ("2", "1")
    assert transition["geometry"] is None  # Never draw a line across floor drawings.
    assert result["scope"] == "multi_floor_drawing_wayfinding"
    assert not result["physical_verification"] and result["distance_m"] is None
    assert not any(s["kind"] == "door" for s in result["steps"][:-1])
    reverse = plan_directions(
        data(), request(start_node_id="exit-threshold", end_node_id="outside-233")
    )
    assert next(s for s in reverse["steps"] if s["kind"] == "elevator")["to_floor"] == "2"


@pytest.mark.parametrize("floor", [None, "1", "2"])
def test_elevator_outage_blocks_cross_floor_route_without_stair_fallback(floor):
    with pytest.raises(RoutingError, match="No drawing connection"):
        plan_directions(data(), request(closures=[closure(floor)]))
    # Same-floor travel remains available.
    assert plan_directions(data(), request(start_node_id="lobby-125", closures=[closure(floor)]))[
        "steps"
    ]


def test_other_floor_incident_does_not_block_and_undocumented_transitions_fail():
    assert plan_directions(data(), request(closures=[closure("3")]))["steps"]
    raw = data().model_dump()
    next(e for e in raw["connections"] if e["kind"] == "elevator")["served_floor_evidence"] = None
    with pytest.raises(ValidationError, match="documented floor stops"):
        PlanWayfindingMap.model_validate(raw)


def test_opt_in_api_rejects_unaccepted_drawing_limits_and_missing_maps(tmp_path):
    atomic_json(tmp_path / "oak.json", data().model_dump(mode="json"))
    with TestClient(
        create_app(engine=RoutingEngine(make_demo_graph()), plan_wayfinding_dir=tmp_path)
    ) as c:
        assert c.get("/plan-wayfinding/oak").status_code == 200
        assert c.get("/plan-wayfinding/unknown").status_code == 404
        result = c.post("/plan-wayfinding/oak", json=request().model_dump(mode="json"))
        assert (
            result.status_code == 200 and result.json()["scope"] == "multi_floor_drawing_wayfinding"
        )
        bad = request(accept_drawing_only=False).model_dump(mode="json")
        assert c.post("/plan-wayfinding/oak", json=bad).status_code == 409
    with TestClient(create_app(engine=RoutingEngine(make_demo_graph()))) as c:
        assert c.get("/plan-wayfinding/oak").status_code == 503
