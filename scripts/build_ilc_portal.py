"""Match the published floor-2 threshold to its explicit OSM level-2 doorway.

The offset historical GIS record is deliberately not an alias for this node.
"""

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from campus_notices.plan_integrity import require_reviewed_source
from campus_routing.drawing_journey import DrawingPortal, DrawingPortalRegistry
from campus_routing.engine import RoutingEngine
from campus_routing.entrance_observations import matching_door_observation, read_door_observations
from campus_routing.plan_wayfinding import PlanWayfindingMap

ROOT = Path(__file__).resolve().parents[1]


def build_portal(root=ROOT):
    plan = PlanWayfindingMap.model_validate_json(
        (root / "data/plan_wayfinding/ilc.json").read_text(encoding="utf-8")
    )
    source = plan.floor_sources["2"]
    image = root / source["local_image"]
    if hashlib.sha256(image.read_bytes()).hexdigest() != source["source_sha256"]:
        raise ValueError("ILC plan image changed; review its threshold again")
    require_reviewed_source("ilc-floor-2.png", source["source_sha256"])
    osm = ET.parse(root / "data/plan_wayfinding/sources/ilc/southwest-approach.osm")
    threshold = osm.find("node[@id='6382267406']")
    way = osm.find("way[@id='1559381819']")
    tags = {t.attrib["k"]: t.attrib["v"] for t in threshold.findall("tag")}
    way_tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
    if tags.get("entrance") != "yes" or tags.get("level") != "2":
        raise ValueError("OSM no longer identifies a level-2 doorway")
    if way_tags.get("highway") != "footway" or way_tags.get("access") in ("no", "private"):
        raise ValueError("Source approach is no longer a public footway")
    if [int(n.attrib["ref"]) for n in way.findall("nd")] != [12878112838, 6382267406]:
        raise ValueError("OSM approach changed")
    node = next(n for n in plan.nodes if n.id == "ilc-entrance-south")
    if node.floor_id != "2" or node.kind != "entrance":
        raise ValueError("Indoor threshold changed floors or kind")
    extent = json.loads(source["extent"])
    x = extent["xmin"] + node.x * (extent["xmax"] - extent["xmin"]) / float(source["width"])
    y = extent["ymax"] - node.y * (extent["ymax"] - extent["ymin"]) / float(source["height"])
    plan_lng = math.degrees(x / 6378137)
    plan_lat = math.degrees(2 * math.atan(math.exp(y / 6378137)) - math.pi / 2)
    lat, lng = float(threshold.attrib["lat"]), float(threshold.attrib["lon"])
    outdoor = RoutingEngine.from_file(root / "data/umass.graph.json")
    gap = math.dist(outdoor.to_xy(lng, lat), outdoor.to_xy(plan_lng, plan_lat))
    anchor = outdoor.graph.nodes[6382267406]
    if gap > 1 or (anchor["lat"], anchor["lng"]) != (lat, lng):
        raise ValueError("Source doorway or outdoor threshold moved")
    approach = outdoor.graph.get_edge_data(6382267406, 12878112838, default={})
    if not any(e.get("kind") == "path" for e in approach.values()):
        raise ValueError("Outdoor approach is absent")
    observation = matching_door_observation(
        read_door_observations(root / "data/reviews/entrance-observations.json"),
        "ilc",
        dict(id="osm-entrance-6382267406", lat=lat, lng=lng, level="2"),
    )
    return DrawingPortal(
        id="ilc-southwest-floor-2",
        building_id="ilc",
        indoor_node_id=node.id,
        floor_id="2",
        outdoor_node_id=6382267406,
        outdoor_approach_node_id=12878112838,
        position=dict(lat=lat, lng=lng),
        entrance_id="osm-entrance-6382267406",
        plan_source_sha256=source["source_sha256"],
        source_urls=[
            source["source_url"],
            "https://www.openstreetmap.org/node/6382267406",
            "https://www.openstreetmap.org/way/1559381819",
        ],
        evidence=f"Published floor-2 southwest threshold aligns within {gap:.2f} m of OSM "
        "entrance 6382267406, explicitly tagged level=2 and terminating footway 1559381819. "
        "User also reports this southwest doorway enters floor 2. Use the existing outdoor "
        "node as the transition; do not draw a connector from historical GIS point 56. "
        "Current access and doorway operation are unverified."
        + (
            f" Opener presence at this doorway was peer-confirmed, relayed "
            f"{observation.reported_on}."
            if observation
            else ""
        ),
        keycard_required=False,
        step_free=True,
        door_type=observation.door_type if observation else "unknown",
        door_evidence=observation,
    )


def main():
    path = ROOT / "data/plan_wayfinding_portals.json"
    registry = (
        DrawingPortalRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        if path.exists()
        else DrawingPortalRegistry()
    )
    portal = build_portal()
    registry.portals = [p for p in registry.portals if p.building_id != "ilc"] + [portal]
    path.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print("ILC southwest floor-2 threshold matched; physical access unverified")


if __name__ == "__main__":
    main()
