import json
from pathlib import Path

from campus_routing.indoor import IndoorEngine, IndoorRouteRequest, read_indoor

ROOT = Path(__file__).resolve().parents[1]


def test_library_source_destination_route_is_available():
    data = read_indoor(ROOT / "data/indoor/library.json")
    result = IndoorEngine(data).route(
        IndoorRouteRequest(
            building_id="library",
            start_node_id="lib-lobby-2nd-floor",
            end_node_id="lib-source-2f9cf0cb673d6873f4c3",
        )
    )
    assert result["node_path"][-1] == "lib-source-2f9cf0cb673d6873f4c3"
    assert any("pilot waypoint" in warning for warning in result["warnings"])


def test_ilc_n151_second_floor_source_destination_route_is_available():
    data = read_indoor(ROOT / "data/indoor/ilc.json")
    result = IndoorEngine(data).route(
        IndoorRouteRequest(
            building_id="ilc",
            start_node_id="ilc-entrance-south",
            end_node_id="ilc-source-n151-f2",
        )
    )
    assert result["floor_sequence"] == ["1", "2"]
    assert result["node_path"][-1] == "ilc-source-n151-f2"
    assert any("pilot waypoint" in warning for warning in result["warnings"])


def test_production_maps_cover_all_source_destinations():
    library = read_indoor(ROOT / "data/indoor/library.json")
    ilc = read_indoor(ROOT / "data/indoor/ilc.json")

    assert sum(node.kind == "room" for node in library.nodes) == 27
    assert sum(node.kind == "room" for node in ilc.nodes) == 16


def test_public_floorplan_manifest_covers_available_library_and_ilc_plans():
    manifest = json.loads((ROOT / "data/indoor/public_floorplans.json").read_text(encoding="utf-8"))
    library = [row for row in manifest["plans"] if row["building_id"] == "library"]
    ilc = [row for row in manifest["plans"] if row["building_id"] == "ilc"]

    assert len(library) == 26
    assert {row["floor_id"] for row in ilc} == {"1", "2"}


def test_ilc_public_plan_trace_uses_image_coordinates_and_reaches_all_rooms():
    data = read_indoor(ROOT / "data/indoor/ilc.json")
    engine = IndoorEngine(data)
    for floor_id in ("1", "2"):
        floor = next(floor for floor in data.floors if floor.id == floor_id)
        assert floor.coordinate_system == "image_pixels"
        assert floor.image_width == 1536
        assert floor.image_height == 1280

    rooms = [node for node in data.nodes if node.kind == "room"]
    for room in rooms:
        start = "ilc-entrance-south" if room.floor_id == "1" else "ilc-elev-west-f1"
        result = engine.route(
            IndoorRouteRequest(
                building_id="ilc",
                start_node_id=start,
                end_node_id=room.id,
            )
        )
        assert result["node_path"][-1] == room.id
