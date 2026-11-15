import pytest

from scripts.audit_indoor_coverage import audit_building
from scripts.connect_brown import connect
from scripts.demo_navigation import pilot_fixtures


def test_audit_checks_each_destination_both_directions_and_empty_floors():
    data = pilot_fixtures()["ilc"].model_copy(update={"synthetic": False})
    report = audit_building(data)
    assert sum(f["room_count"] for f in report["floors"]) == 1
    room = next(f for f in report["floors"] if f["room_count"])["destinations"][0]
    assert room["reachable_from_entrance"] and room["can_return_to_entrance"]
    scenarios = {s["scenario"]: s for s in report["elevator_outage_checks"]}
    assert scenarios["ilc-lift-a"]["destinations"][0]["route_available"]
    assert not scenarios["all_elevators"]["destinations"][0]["route_available"]
    assert all(
        f["physical_verification"] == "not_established_by_route_test" for f in report["floors"]
    )


def test_brown_connector_does_not_recreate_inferred_stops(tmp_path):
    with pytest.raises(ValueError, match="inference is disabled"):
        connect(tmp_path / "source.json", tmp_path / "output.json")
    assert not (tmp_path / "output.json").exists()
