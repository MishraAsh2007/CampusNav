"""Combining source positions must not invent accessibility or completeness."""

from datetime import UTC, datetime

import httpx
import pytest

from scripts import sync_campus_access as sync


def test_source_merge_keeps_provenance_and_unknowns(monkeypatch):
    monkeypatch.setattr(sync, "BUILDINGS", {"413": sync.BUILDINGS["413"]})
    data = {
        "buildings": [
            {
                "attributes": {
                    "OBJECTID": 1,
                    "BuildingID": "413",
                    "AccessLevel": "Fully Accessible",
                },
                "geometry": {
                    "rings": [
                        [
                            [-72.529, 42.391],
                            [-72.527, 42.391],
                            [-72.527, 42.392],
                            [-72.529, 42.392],
                            [-72.529, 42.391],
                        ]
                    ]
                },
            }
        ],
        "entrances": [
            {
                "attributes": {
                    "OBJECTID": 73,
                    "hasAutoDoorOpener": 1,
                    "isAccessibleToAllFloors": 1,
                    "IsKeyCardRequired": 0,
                },
                "geometry": {"x": -72.528, "y": 42.391},
            }
        ],
        "elevators": [{"attributes": {"OBJECTID": 141}, "geometry": {"x": -72.528, "y": 42.3915}}],
    }
    osm = {
        "elements": [
            {"type": "node", "id": 100, "lat": 42.392, "lon": -72.528, "tags": {"entrance": "yes"}},
            {
                "type": "node",
                "id": 101,
                "lat": 42.391,
                "lon": -72.528,
                "tags": {"entrance": "yes", "wheelchair": "no"},
            },
        ]
    }
    catalog, assets = sync.normalize(data, osm, datetime.now(UTC))
    building = catalog["buildings"][0]
    official, extra = building["entrances"]
    assert official["step_free"] is False  # source disagreement excludes this door
    assert official["supplemental_sources"] == ["https://www.openstreetmap.org/node/101"]
    assert extra["step_free"] is None
    assert extra["door_type"] == "unknown"
    assert building["elevators"]["total_count"] is None
    assert len(assets) == building["elevators"]["mapped_locations"] == 1
    assert "no indoor graph connection" in assets[0]["evidence"]


def test_failed_or_repeated_arcgis_page_is_not_accepted_as_complete():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json={"features": [{"attributes": {"OBJECTID": 1}}], "exceededTransferLimit": True}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="Repeated"):
            sync.fetch_layer(client, "Entrances", "OBJECTID")
    assert len(calls) == 2
    assert calls[1].url.params["resultOffset"] == "1000"
