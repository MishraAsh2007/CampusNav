from copy import deepcopy

from campus_notices.entrance_evidence import supplement


def fixture():
    shape = {"attributes": {"BuildingID": "704", "BuildingName": "ILC"},
             "geometry": {"rings": [[[-72.527, 42.39], [-72.526, 42.39],
                                      [-72.526, 42.391], [-72.527, 42.391],
                                      [-72.527, 42.39]]]}}
    row = {"attributes": {"OBJECTID": 999, "OBJECTID_1": 56, "hasAutoDoorOpener": 1,
                          "isKeyCardRequired": 0, "isAccessible": 1,
                          "last_edited_date": 1564162947000},
           "geometry": {"x": -72.5265, "y": 42.39}}
    catalog = {"buildings": [{"id": "ilc", "name": "ILC", "category": "academic",
                             "location": {"lat": 42.3905, "lng": -72.5265},
                             "in_routing_area": True, "entrances": []}]}
    return catalog, {"buildings": [shape], "entrances": [], "legacy_entrances": [row]}


def test_adds_dated_source_record_without_claiming_current_operation_and_is_idempotent():
    catalog, source = fixture()
    result, audit = supplement(catalog, source, "2026-11-15T00:00:00Z")
    entry = result["buildings"][0]["entrances"][0]
    assert entry["id"] == "umass-legacy-entrance-56"
    assert entry["source_url"].endswith("/56")  # real service OID, not OBJECTID=999
    assert entry["door_type"] == "push-button" and entry["step_free"] is True
    assert entry["source_record_date"] == "2019-07-26"
    assert entry["current_operation_verified"] is False
    assert audit[0]["decision"] == "added_dated_entrance"
    assert catalog["buildings"][0]["entrances"] == []
    again, _ = supplement(result, source, "2026-11-15T00:00:00Z")
    assert again == result


def test_newer_manual_door_record_blocks_older_powered_record():
    catalog, source = fixture()
    source["entrances"] = [{"geometry": source["legacy_entrances"][0]["geometry"],
                            "attributes": {"hasAutoDoorOpener": 0}}]
    result, audit = supplement(catalog, source, "now")
    assert not result["buildings"][0]["entrances"]
    assert audit[0]["decision"] == "current_map_takes_precedence"


def test_nearby_unselected_building_prevents_wrong_spatial_assignment():
    catalog, source = fixture()
    other = deepcopy(source["buildings"][0])
    other["attributes"] = {"BuildingID": "999", "BuildingName": "Other"}
    source["buildings"].append(other)
    result, audit = supplement(catalog, source, "now")
    assert not result["buildings"][0]["entrances"]
    assert audit[0]["decision"] == "ambiguous_building"


def test_keycard_inaccessible_and_residential_records_are_not_promoted():
    for field, value in [("isKeyCardRequired", 1), ("isKeyCardRequired", None),
                         ("isAccessible", 0), ("hasAutoDoorOpener", None)]:
        catalog, source = fixture()
        source["legacy_entrances"][0]["attributes"][field] = value
        assert not supplement(catalog, source, "now")[0]["buildings"][0]["entrances"]
    catalog, source = fixture()
    catalog["buildings"][0]["category"] = "residential"
    assert supplement(catalog, source, "now")[0]["buildings"] == catalog["buildings"]
