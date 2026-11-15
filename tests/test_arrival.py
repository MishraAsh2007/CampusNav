from campus_routing.arrival import matched_arrival
from campus_routing.engine import RoutingEngine
from campus_routing.models import Coordinate, RouteRequest
from scripts.demo_indoor import demo_map
from scripts.make_demo import make_demo_graph


def fixture():
    outdoor = RoutingEngine(make_demo_graph())
    data = demo_map()
    route = outdoor.route(
        RouteRequest(
            start=Coordinate(lat=42.391, lng=-72.528), end=Coordinate(lat=42.392, lng=-72.528)
        )
    )
    return outdoor, data, route


def match(outdoor, data, route, entrance):
    return matched_arrival(
        outdoor, route, entrance, data.building_id, {n.id: n for n in data.nodes}, data.portals
    )


def test_outdoor_arrival_uses_the_shared_graph_node_to_identify_the_indoor_entry():
    outdoor, data, route = fixture()
    result = match(outdoor, data, route, dict(id="osm-entrance-2", osm_id=2))
    assert result["node_id"] == "entrance" and result["floor_id"] == "1"
    assert result["portal_id"] == "demo-entrance-link"


def test_nearby_coordinates_and_building_meeting_points_do_not_substitute_for_entrance_identity():
    outdoor, data, route = fixture()
    assert match(outdoor, data, route, dict(id="another-door", lat=42.392, lng=-72.528)) is None
    assert (
        match(outdoor, data, route, dict(id="osm-entrance-2", osm_id=2, approach_only=True)) is None
    )
    data.portals[0].geometry[-1] = (-72.53, 42.392)
    assert match(outdoor, data, route, dict(id="osm-entrance-2", osm_id=2)) is None


def test_declared_source_identity_requires_the_route_to_reach_that_portal_anchor():
    outdoor, data, route = fixture()
    node = next(n for n in data.nodes if n.id == "entrance")
    node.source_record_ids = ["official-entrance"]
    assert match(outdoor, data, route, dict(id="official-entrance"))["node_id"] == node.id
    route.geometry.coordinates[-1] = (-72.528, 42.391)
    assert match(outdoor, data, route, dict(id="official-entrance")) is None
