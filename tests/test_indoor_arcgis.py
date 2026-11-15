from datetime import timedelta

import httpx
import pytest

from campus_notices.cache import atomic_json
from campus_notices.indoor_arcgis import GIS_SOURCES, fetch_references, parse_features
from campus_notices.indoor_sources import refresh_indoor_sources
from campus_routing.indoor import IndoorMap
from campus_routing.places import LocationQuery, PlaceResolver
from scripts.demo_indoor import NOW
from scripts.demo_navigation import pilot_fixtures


def study_feature(oid=1):
    return dict(
        attributes=dict(
            OBJECTID=oid, Title="Integrative Learning Center: N201", Floor="01", RoomNumber="N201"
        ),
        geometry=dict(x=-72.5266, y=42.3918),
    )


def page(features, **kwargs):
    return dict(features=features, spatialReference=dict(wkid=4326), **kwargs)


def test_explicit_source_floor_is_kept_even_when_room_number_suggests_another():
    rows = parse_features("umass-study-spaces", page([study_feature()]), NOW)
    assert rows[0]["floor_label"] == "01"
    assert rows[0]["room_id"] == "N201"
    assert rows[0]["public_access"] is None and rows[0]["routing_eligible"] is False
    resolver = PlaceResolver({}, dict(records=rows))
    assert resolver.floors("ilc")[0]["id"] == "1"
    result = resolver.resolve(LocationQuery(text="ILC N201"))
    assert result["status"] == "coverage_unavailable" and "endpoint" not in result
    assert result["source_references"][0]["position"]["lat"] == 42.3918


def test_staff_restroom_remains_a_reference_not_a_public_route():
    feature = study_feature()
    feature["attributes"] = dict(
        OBJECTID=1,
        BuildingName="DuBois Library",
        FLOOR="02",
        RoomName="201",
        DESCRIPTION="Staff only",
        ADA="Yes",
    )
    record = parse_features("umass-restrooms", page([feature]), NOW)[0]
    assert record["public_access"] is False
    assert record["routing_eligible"] is False
    assert record["source_attributes"]["ADA"] == "Yes"


def test_paginated_map_advances_by_actual_page_length_and_rejects_repeats():
    offsets = []

    def handler(request):
        offset = int(request.url.params["resultOffset"])
        offsets.append(offset)
        return httpx.Response(
            200, json=page([study_feature(offset + 1)], exceededTransferLimit=offset == 0)
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = fetch_references("umass-study-spaces", client, NOW)
    assert offsets == [0, 1] and len(rows) == 2
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json=page([study_feature()], exceededTransferLimit=True)
                )
            )
        ) as client,
        pytest.raises(ValueError, match="Repeated public map page"),
    ):
        fetch_references("umass-study-spaces", client, NOW)


@pytest.mark.parametrize(
    "payload",
    [
        page([study_feature()], exceededTransferLimit=True),
        dict(features=[study_feature()], spatialReference=dict(wkid=3857)),
        dict(error=dict(code=403)),
        page([dict(attributes=None, geometry=None)]),
        page([dict(attributes=study_feature()["attributes"], geometry=dict(x=0, y=0))]),
        page([]),
        [],
    ],
)
def test_invalid_or_partial_map_data_cannot_be_promoted(payload):
    with pytest.raises(ValueError):
        parse_features("umass-study-spaces", payload, NOW)


def test_later_page_failure_retains_whole_prior_source_and_original_timestamp(tmp_path):
    key = "umass-study-spaces"
    rows = parse_features(key, page([study_feature(80)]), NOW)
    path = tmp_path / "sources.json"
    atomic_json(path, dict(records=rows, sources={key: dict(observed_at=NOW.isoformat())}))

    def handler(request):
        if request.url.path == httpx.URL(GIS_SOURCES[key]["url"] + "/query").path:
            if request.url.params["resultOffset"] == "0":
                return httpx.Response(200, json=page([study_feature()], exceededTransferLimit=True))
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = refresh_indoor_sources(path, client=client, now=NOW + timedelta(hours=1))
    assert result["records"] == rows
    assert result["sources"][key]["mode"] == "cache"
    assert result["sources"][key]["observed_at"] == NOW.isoformat()


def test_source_record_requires_an_explicit_reviewed_node_binding():
    rows = parse_features("umass-study-spaces", page([study_feature()]), NOW)
    maps = pilot_fixtures()
    resolver = PlaceResolver(maps, dict(records=rows), allow_synthetic=True)
    assert resolver.resolve(LocationQuery(text="ILC N201"))["status"] == "coverage_unavailable"
    raw = maps["ilc"].model_dump(mode="json")
    node = next(n for n in raw["nodes"] if n["id"] == "entrance")
    node["source_record_ids"] = [rows[0]["id"]]  # Fictional test binding only.
    maps["ilc"] = IndoorMap.model_validate(raw)
    resolved = resolver.resolve(LocationQuery(text="ILC N201 on floor 01"))
    assert resolved["endpoint"]["node_id"] == "entrance"
    assert resolved["floor_id"] == "1"
    assert (
        resolver.resolve(LocationQuery(text="ILC N201 on floor 2"))["status"]
        == "coverage_unavailable"
    )
