import httpx
import pytest

from campus_notices.library_elevators import (
    collect,
    elevator_regions,
    floor_references,
    historical_service,
)


def test_floor_identity_excludes_other_library_and_collapses_portrait_duplicate():
    card = """<div class="analytics-card" data-loc="16"><h1>W. E. B. Du Bois Library</h1>
    <h2>1st Floor</h2><img src="/media/maps/1st.png"></div>"""
    other = card.replace("W. E. B. Du Bois Library", "Science &amp; Engineering Library")
    rows = floor_references(card + card + other)
    assert len(rows) == 1 and rows[0]["source_floor_id"] == "16"
    with pytest.raises(ValueError, match="Conflicting"):
        floor_references(card + card.replace("1st Floor", "2nd Floor"))


def test_regions_preserve_group_bounds_without_creating_cars():
    html = """<script>var navState={"floor_map_dimensions":{'width':1270,'height':1500}};</script>
    <div class="places-item" aria-label="Elevator" id="place-51"
    x="490" y="592" width="72" height="173"></div>"""
    result = elevator_regions(html)
    assert result["regions"][0]["bounds"]["height"] == 173
    assert result["regions"][0]["physical_car_id"] is None
    assert result["regions"][0]["routing_eligible"] is False
    with pytest.raises(ValueError, match="outside"):
        elevator_regions(html.replace('x="490"', 'x="1260"'))


def test_historical_car_service_cannot_be_used_as_current_topology():
    text = """7/9/07
    Elevators #1 and #2 go to Main, Entrance/Exit, and Express to 16-26
    Elevators #3, #4 and #5 go to Main, and Entrance/Exit-16"""
    rows = historical_service(text)
    assert [r["source_car_label"] for r in rows] == ["#1", "#2", "#3", "#4", "#5"]
    assert "express" in rows[0]["service_description"]
    assert all(not r["current_service_confirmed"] and not r["routing_eligible"] for r in rows)
    with pytest.raises(ValueError, match="changed"):
        historical_service(text.replace("7/9/07", "11/14/26"))


def test_partial_refresh_preserves_previous_evidence_file(tmp_path):
    output = tmp_path / "sources.json"
    output.write_text('{"previous":"complete"}', encoding="utf-8")
    index = """<div class="analytics-card" data-loc="16"><h1>W. E. B. Du Bois Library</h1>
    <h2>1st Floor</h2><img src="/media/maps/1st.png"></div>"""

    def respond(request):
        if request.url.path == "/explore/":
            return httpx.Response(200, text=index)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            collect(output, tmp_path / "cache", client)
    assert output.read_text(encoding="utf-8") == '{"previous":"complete"}'
