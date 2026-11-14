import pymupdf
import pytest

from campus_routing.engine import RoutingError
from campus_routing.plan_wayfinding import PlanWayfindingRequest, plan_directions
from scripts.expand_oak_wayfinding import extend
from scripts.trace_oak_wayfinding import build


def test_explicit_grouped_floor_template_gets_distinct_hall_landmarks_and_stops(tmp_path):
    records = {}
    sources = {}
    for floor in ["1", "2", "3", "4", "5", "6"]:
        path = tmp_path / (floor + ".pdf")
        with pymupdf.open() as doc:
            page = doc.new_page(width=792, height=612)
            text = "-33" if floor in ["3", "4"] else floor + "33"
            page.insert_text((330, 330), text)
            doc.save(path)
        records[floor] = dict(local_path=str(path))
        sources[floor] = dict(url=f"https://example.com/{floor}.pdf", sha256="a" * 64)
    data, counts = extend(build(sources), records, sources)
    assert set(data.floor_sources) == set("123456")
    assert counts["3"] == counts["4"] == 1
    ids = {n.id for n in data.nodes}
    assert "near-333" in ids and "near-433" in ids
    req = PlanWayfindingRequest(
        start_node_id="near-633",
        end_node_id="exit-threshold",
        accept_drawing_only=True,
        resident_access_confirmed=True,
    )
    route = plan_directions(data, req)
    assert any(s["from_floor"] == "6" for s in route["steps"])
    assert route["steps"][-1]["to_floor"] == "1"
    rides = [s for s in route["steps"] if s["kind"] == "elevator"]
    assert len(rides) == 1 and rides[0]["from_floor"] == "6" and rides[0]["to_floor"] == "1"
    assert len(rides[0]["connection_ids"]) == 5
    # The builder does not fabricate a step-free first-floor wing-to-lobby link.
    if "near-133" in ids:
        with pytest.raises(RoutingError, match="No drawing connection"):
            plan_directions(data, req.model_copy(update={"start_node_id": "near-133"}))
