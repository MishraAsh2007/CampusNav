"""Identify the exact indoor landing selected by an outdoor building route.

This is an identity join through declared source IDs or a shared OSM graph node,
never a nearest-entrance guess or a claim about the user's current GPS location.
"""

from shapely.geometry import Point


def matched_arrival(outdoor, route, entrance, building_id, nodes, portals):
    if not route or not entrance or entrance.get("approach_only"):
        return None
    end = Point(outdoor.to_xy(*route.geometry.coordinates[-1]))
    matches = []
    for portal in portals:
        node = nodes.get(portal.indoor_node_id)
        if not node or portal.outdoor_node_id not in outdoor.node_anchors:
            continue
        refs = getattr(node, "source_record_ids", [])
        identity = (
            entrance["id"] in refs
            or entrance["id"] == getattr(portal, "entrance_id", None)
            or (entrance.get("osm_id") is not None and entrance["osm_id"] == portal.outdoor_node_id)
        )
        if not identity:
            continue
        anchor = outdoor.graph.nodes[portal.outdoor_node_id]
        point = Point(outdoor.to_xy(anchor["lng"], anchor["lat"]))
        declared = Point(outdoor.to_xy(*portal.geometry[-1]))
        if point.distance(declared) > 1 or end.distance(point) > 1:
            continue  # Outdoor route must actually reach this portal's network anchor.
        matches.append(
            dict(
                building_id=building_id,
                node_id=node.id,
                floor_id=node.floor_id or getattr(portal, "floor_id", None),
                label=node.label,
                portal_id=portal.id,
                entrance_id=entrance["id"],
                match_basis="declared_entrance_identity_and_reached_graph_anchor",
            )
        )
    return matches[0] if len(matches) == 1 else None
