"""Outdoor meeting points for halls without a mapped doorway.

These are walking-network destinations outside the footprint, never entrances.
"""

import networkx as nx
from pyproj import Transformer
from shapely import transform
from shapely.geometry import Polygon
from shapely.ops import nearest_points, unary_union


def add_network_approaches(catalog, source, engine, specs, *, max_gap_m=100):
    project = Transformer.from_crs(4326, 32618, always_xy=True).transform
    inverse = Transformer.from_crs(32618, 4326, always_xy=True).transform
    shapes = {}
    component = max(nx.weakly_connected_components(engine.graph), key=len)
    connected_lines = [
        (i, line) for i, line in enumerate(engine.lines) if engine.edge_ids[i][0] in component
    ]
    for feature in source["buildings"]:
        key = str(feature["attributes"]["BuildingID"])
        if key not in specs:
            continue
        geometry = unary_union([Polygon(r).buffer(0) for r in feature["geometry"]["rings"]])
        shapes[specs[key][0]] = transform(geometry, project, interleaved=False)
    for building in catalog["buildings"]:
        if building["category"] != "residential" or building["entrances"]:
            continue
        footprint = shapes[building["id"]]
        candidates = sorted(connected_lines, key=lambda row: footprint.distance(row[1]))
        for _, line in candidates:
            gap = footprint.distance(line)
            if gap > max_gap_m:
                break
            boundary, meeting = nearest_points(footprint, line)
            if footprint.covers(meeting) or gap < 1:
                continue
            lng, lat = inverse(meeting.x, meeting.y)
            building["entrances"].append(
                dict(
                    id="network-approach-" + building["id"],
                    name="Outdoor meeting point; entrance not mapped",
                    lat=lat,
                    lng=lng,
                    approach_only=True,
                    step_free=None,
                    door_type="unknown",
                    keycard_required=None,
                    in_routing_area=True,
                    source="OSM walking network near official building footprint",
                    source_url="https://www.openstreetmap.org/copyright",
                    building_gap_m=round(gap, 2),
                    notes="Ends on a mapped outdoor path. No connection to a door has "
                    "been established; find an entrance locally. Not an indoor route.",
                )
            )
            break
    return catalog
