import json
from copy import deepcopy
from pathlib import Path

from campus_routing.entrance_observations import apply_door_observations, read_door_observations

ROOT = Path(__file__).resolve().parents[1]


def test_peer_opener_evidence_is_scoped_and_survives_source_refresh():
    catalog = json.loads((ROOT / "data/buildings.json").read_text(encoding="utf-8"))
    observations = read_door_observations(ROOT / "data/reviews/entrance-observations.json")
    original = deepcopy(catalog)
    building = next(b for b in catalog["buildings"] if b["id"] == "ilc")
    target = next(e for e in building["entrances"] if e["id"] == "osm-entrance-6382267406")
    target["door_type"] = "unknown"  # A refreshed OSM snapshot has no opener tag.
    target.pop("door_evidence", None)
    result = apply_door_observations(catalog, observations)
    updated = next(b for b in result["buildings"] if b["id"] == "ilc")
    door = next(e for e in updated["entrances"] if e["id"] == target["id"])
    assert door["door_type"] == "push-button"
    assert door["door_evidence"]["observed_on"] is None
    assert door["current_operation_verified"] is False
    assert door["step_free"] == target["step_free"]  # An opener does not measure the threshold.
    assert target["door_type"] == "unknown"
    assert apply_door_observations(result, observations) == result
    for before, after in zip(building["entrances"], updated["entrances"], strict=True):
        if before["id"] != target["id"]:
            assert before == after
    assert [b for b in result["buildings"] if b["id"] != "ilc"] == [
        b for b in original["buildings"] if b["id"] != "ilc"
    ]


def test_observation_does_not_transfer_to_another_floor_or_relocated_door():
    records = read_door_observations(ROOT / "data/reviews/entrance-observations.json")
    entry = dict(
        id=records[0].entrance_id, lat=42.3908286, lng=-72.5262556, level="2", door_type="unknown"
    )
    for changes in ({"level": "1"}, {"lat": 42.3909}, {"id": "umass-legacy-entrance-56"}):
        catalog = {"buildings": [{"id": "ilc", "entrances": [entry | changes]}]}
        assert apply_door_observations(catalog, records) == catalog
