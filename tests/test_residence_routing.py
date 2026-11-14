import pytest

from campus_routing.buildings import Place, TripRequest, choices, plan_trip
from campus_routing.engine import RoutingEngine
from campus_routing.residences import add_network_approaches
from scripts.build_residence_catalog import residence_specs
from scripts.make_demo import make_demo_graph


def test_plan_inventory_matches_official_building_code_and_named_alias():
    records = [
        dict(building="Brown Hall", name="426-01.pdf"),
        dict(building="Wheeler", name="Wheeler-1.pdf"),
    ]
    features = [
        dict(attributes=dict(BuildingID="426", BuildingName="Brown House")),
        dict(attributes=dict(BuildingID="033", BuildingName="Wheeler House")),
    ]
    specs, missing = residence_specs(records, features)
    assert not missing and specs["426"][0] == "brown-house" and specs["033"][0] == "wheeler"


def test_keycard_approach_is_explicit_and_still_an_outdoor_trip():
    entry = dict(
        id="entry",
        name="Keycard door",
        lat=42.392,
        lng=-72.528,
        keycard_required=True,
        step_free=True,
        door_type="manual",
    )
    catalog = dict(
        buildings=[dict(id="hall", name="Hall", in_routing_area=True, entrances=[entry])]
    )
    place = Place(lat=42.392, lng=-72.528, building_id="hall")
    from campus_routing.engine import RoutingError

    with pytest.raises(RoutingError, match="No mapped public entrance"):
        choices(place, catalog, step_free=True, automatic=False)
    request = TripRequest(
        origin=dict(lat=42.391, lng=-72.528),
        destination=place,
        allow_keycard_entrance_approach=True,
    )
    result = plan_trip(RoutingEngine(make_demo_graph()), catalog, request)
    assert result["accessible"] is not None
    assert any("ends outside" in n for n in result["notes"])
    assert entry["keycard_required"] is True


def test_network_meeting_point_is_outside_footprint_and_never_claims_a_door():
    source = dict(
        buildings=[
            dict(
                attributes=dict(BuildingID="426"),
                geometry=dict(
                    rings=[
                        [
                            [-72.5285, 42.3914],
                            [-72.5284, 42.3914],
                            [-72.5284, 42.3915],
                            [-72.5285, 42.3915],
                            [-72.5285, 42.3914],
                        ]
                    ]
                ),
            )
        ]
    )
    catalog = dict(buildings=[dict(id="brown-house", category="residential", entrances=[])])
    engine = RoutingEngine(make_demo_graph())
    add_network_approaches(catalog, source, engine, {"426": ("brown-house",)})
    entry = catalog["buildings"][0]["entrances"][0]
    assert entry["approach_only"] and entry["step_free"] is None
    assert entry["building_gap_m"] > 1
    from shapely.geometry import Point, Polygon

    assert not Polygon(source["buildings"][0]["geometry"]["rings"][0]).covers(
        Point(entry["lng"], entry["lat"])
    )
    assert "entrance not mapped" in entry["name"]
