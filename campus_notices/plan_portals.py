"""Review explicit plan/entrance/OSM identities; never auto-join nearest coordinates."""

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from shapely.geometry import Point

from campus_routing.drawing_journey import DrawingPortal, DrawingPortalRegistry
from campus_routing.engine import RoutingEngine
from campus_routing.plan_wayfinding import PlanWayfindingMap

from .cache import atomic_json
from .plan_integrity import REVIEWED_HASHES

NORTH_NODE = 2264382900
NORTH_POSITION = (-72.5252027, 42.3967152)
NORTH_BUILDING_WAY = 216955127
NORTH_FOOTWAY = 217134889
MAP_SERVICE = "https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services"


def north_portal(gis, osm, outdoor, plan):
    """The drawing-bottom lobby exit is geographic southwest on the rotated North D plan."""
    entrance = next(r for r in gis["entrances"] if r["attributes"]["OBJECTID"] == 50)
    attributes = entrance["attributes"]
    if attributes.get("isAccessibleToAllFloors") != 1:
        raise ValueError("Official entrance no longer states all-floor accessibility")
    points = {int(n.attrib["id"]): n for n in osm.findall("node")}
    ways = {int(w.attrib["id"]): w for w in osm.findall("way")}
    node = points[NORTH_NODE]
    position = (float(node.attrib["lon"]), float(node.attrib["lat"]))
    if math.dist(position, NORTH_POSITION) > 1e-8:
        raise ValueError("Reviewed threshold node moved; re-inspect entrance alignment")
    building, path = ways[NORTH_BUILDING_WAY], ways[NORTH_FOOTWAY]
    building_nodes = [int(n.attrib["ref"]) for n in building.findall("nd")]
    path_nodes = [int(n.attrib["ref"]) for n in path.findall("nd")]
    tags = {t.attrib["k"]: t.attrib["v"] for t in path.findall("tag")}
    if (
        NORTH_NODE not in building_nodes
        or NORTH_NODE not in [path_nodes[0], path_nodes[-1]]
        or tags.get("highway") != "footway"
        or tags.get("access") in ("no", "private")
    ):
        raise ValueError("Threshold must lie on the documented building and footway endpoint")
    if len(path_nodes) != 2 or not outdoor.graph.has_edge(*path_nodes):
        raise ValueError("Reviewed approach footway is absent from the active graph")
    if any(e.get("kind") == "steps" for e in outdoor.graph[path_nodes[0]][path_nodes[1]].values()):
        raise ValueError("Reviewed approach has steps")
    p = entrance["geometry"]
    distance = Point(outdoor.to_xy(*position)).distance(Point(outdoor.to_xy(p["x"], p["y"])))
    if distance > 4:
        raise ValueError("Official southwest entrance no longer corroborates this threshold")
    source = plan.floor_sources["1"]
    if source["sha256"] != REVIEWED_HASHES["673-01.pdf"]:
        raise ValueError("North D first-floor edition changed; re-inspect threshold")
    return DrawingPortal(
        id="north-d-southwest",
        building_id="north-d",
        indoor_node_id="exit-threshold-1",
        floor_id="1",
        outdoor_node_id=NORTH_NODE,
        outdoor_approach_node_id=next(n for n in path_nodes if n != NORTH_NODE),
        position=dict(lng=position[0], lat=position[1]),
        entrance_id="umass-entrance-50",
        plan_source_sha256=source["sha256"],
        keycard_required=bool(attributes["IsKeyCardRequired"]),
        step_free=True,
        door_type="push-button" if attributes["hasAutoDoorOpener"] else "manual",
        source_urls=[
            source["url"],
            f"{MAP_SERVICE}/Entrances/FeatureServer/0/50",
            f"https://www.openstreetmap.org/node/{NORTH_NODE}",
            f"https://www.openstreetmap.org/way/{NORTH_FOOTWAY}",
            f"https://www.openstreetmap.org/way/{NORTH_BUILDING_WAY}",
        ],
        evidence="The rotated first-floor drawing's bottom lobby vestibule corresponds to the "
        "southwest side. OSM node 2264382900 is shared by the North D building outline and "
        "the end of footway 217134889. Official entrance 50 corroborates the southwest door "
        f"within {distance:.2f} m and labels keycard/push-button/all-floor access. "
        "Use the OSM boundary node as the common threshold; no walkway is interpolated "
        "from the offset GIS point. Source inspection only; current access is unverified.",
    )


def collect(root):
    gis_path = root / ".cache/residence-access.json"
    osm_path = root / ".cache/residence-map.osm"
    gis = json.loads(gis_path.read_text(encoding="utf-8"))
    osm = ET.parse(osm_path).getroot()
    outdoor = RoutingEngine.from_file(root / "data/umass-residences.graph.json")
    folder = root / "data/private/plan_wayfinding"
    registry = DrawingPortalRegistry(
        generated_at=datetime.now(UTC).isoformat(),
        unresolved=[
            dict(
                building_id="old-chapel",
                indoor_node_id="entry-threshold-1",
                reason="The cached OSM entrance 14181661922 is a historic stair-side door. "
                "The accessible pavilion door lacks an established exact path/threshold match.",
            ),
            dict(
                building_id="goodell",
                indoor_node_id="west-entry-3",
                reason="The west level-3 doorway lacks a current exact outdoor graph threshold. "
                "Official GIS entrance 75 is on the north approach and cannot be substituted.",
            ),
            dict(
                building_id="goodell",
                indoor_node_id="east-entry-5",
                reason="Official directions identify the level-5 column entry, but an exact "
                "door-to-walking-graph connection is not established.",
            ),
        ],
    )
    try:
        plan = PlanWayfindingMap.model_validate_json((folder / "north-d.json").read_text())
        registry.portals.append(north_portal(gis, osm, outdoor, plan))
    except (KeyError, StopIteration, ValueError, OSError) as exc:
        registry.unresolved.append(
            dict(building_id="north-d", indoor_node_id="exit-threshold-1", reason=str(exc))
        )
    # Failed revalidation removes eligibility; stale matches must not silently survive.
    result = registry.model_dump(mode="json")
    result["source_observed_at"] = gis.get("observed_at")
    result["source_fingerprints"] = {
        "campus_map": hashlib.sha256(gis_path.read_bytes()).hexdigest(),
        "osm_extract": hashlib.sha256(osm_path.read_bytes()).hexdigest(),
    }
    atomic_json(root / "data/private/plan_wayfinding_portals.json", result)
    return registry
