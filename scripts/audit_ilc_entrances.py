"""Join source evidence for review without promoting nearby points into doorways."""

import json
import math
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from campus_routing.entrance_observations import read_door_observations

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/plan_wayfinding/sources/ilc"


def audit():
    gis = json.loads((SOURCE / "entrance-records.json").read_text(encoding="utf-8"))
    osm = ET.parse(SOURCE / "osm-building.osm")
    nodes = {int(n.attrib["id"]): n for n in osm.findall("node")}
    graph = json.loads((ROOT / "data/umass.graph.json").read_text(encoding="utf-8"))
    graph_nodes = {n["id"] for n in graph["nodes"]}
    observations = read_door_observations(ROOT / "data/reviews/entrance-observations.json")
    specs = {
        55: (
            "North",
            None,
            "1",
            "ilc-entrance-north-f1",
            "Plan doorway has no exact connected outdoor threshold. Establish the outer "
            "door position and intervening path; the current indoor landmark is inside the lobby.",
        ),
        56: (
            "Southwest",
            6382267406,
            "2",
            "ilc-entrance-south",
            "OSM threshold and floor-2 plan are matched. A peer independently confirmed "
            "opener presence at this floor-2 doorway, relayed 15 November 2026. "
            "The historical GIS point remains offset and is not a routing alias. "
            "The final mapped path has an estimated 6.5% grade, retained by routing.",
        ),
        57: (
            "Southeast / North Pleasant Street",
            6382267407,
            "2",
            None,
            "OSM labels the doorway level 2 but has no attached walking way. Trace the "
            "floor-2 vestibule/corridor and establish a real outdoor approach, including "
            "stairs, slope and door identity, before enabling a handoff.",
        ),
    }
    rows = []
    for record in gis["features"]:
        attrs, position = record["attributes"], record["geometry"]
        oid = attrs["OBJECTID_1"]
        if oid not in specs:
            continue
        name, node_id, floor, indoor_node, missing = specs[oid]
        node = nodes.get(node_id)
        distance = None
        if node is not None:
            lat, lng = float(node.attrib["lat"]), float(node.attrib["lon"])
            distance = math.hypot(
                (position["y"] - lat) * 111320,
                (position["x"] - lng) * 111320 * math.cos(math.radians(lat)),
            )
        edges = [e for e in graph["edges"] if e["u"] == node_id]
        rows.append(
            dict(
                name=name,
                official_record_id=oid,
                source_url=f"https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/Entrances_PNTS/FeatureServer/0/{oid}",
                record_date=datetime.fromtimestamp(attrs["last_edited_date"] / 1000, UTC)
                .date()
                .isoformat(),
                documents_opener=attrs.get("hasAutoDoorOpener") == 1,
                documents_all_floor_access=attrs.get("isAccessibleToAllFloors") == 1,
                official_record_floor=None,
                current_operation_verified=False,
                peer_door_evidence=[
                    observation.model_dump(mode="json")
                    for observation in observations
                    if observation.building_id == "ilc"
                    and observation.entrance_id == f"osm-entrance-{node_id}"
                ],
                position=position,
                candidate_osm_node=node_id,
                candidate_floor=floor,
                existing_indoor_node=indoor_node,
                point_offset_m=round(distance, 2) if distance is not None else None,
                outdoor_graph_contains_node=node_id in graph_nodes,
                outgoing_edges=len(edges),
                missing=missing,
                automatic_promotion=False,
            )
        )
    return dict(
        building_id="ilc",
        source_observed_on="2026-11-15",
        entrances=rows,
        rule="A documented opener at an offset point is not a surveyed doorway identity.",
    )


if __name__ == "__main__":
    report = audit()
    target = ROOT / "data/reviews/ilc-entrance-audit.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["entrances"]:
        print(
            row["name"],
            "opener documented:",
            row["documents_opener"],
            "graph edges:",
            row["outgoing_edges"],
        )
