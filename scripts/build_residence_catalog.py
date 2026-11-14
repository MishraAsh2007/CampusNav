"""Join downloaded dorm inventory to official public building/entrance footprints."""

import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_notices.residence_workspace import building_identity
from campus_routing.engine import RoutingEngine
from campus_routing.residences import add_network_approaches
from scripts.sync_campus_access import BUILDINGS, normalize

ROOT = Path(__file__).resolve().parents[1]
BBOX = (-72.541, 42.381, -72.512, 42.401)


def residence_specs(records, features):
    specs = dict(BUILDINGS)
    public = {str(r["attributes"]["BuildingID"]): r["attributes"] for r in features}
    lookup = {building_identity(r["BuildingName"]): key for key, r in public.items()}
    missing = []
    for record in records:
        name = record["building"]
        ident = building_identity(name)
        code = re.match(r"^(\d{3})-", record["name"])
        key = code[1] if code and code[1] in public else lookup.get(ident)
        if key is None:
            missing.append(dict(building=name, source_file=record["name"]))
            continue
        aliases = [name, name.removesuffix(" Hall"), public[key]["BuildingName"]]
        specs[key] = (ident, public[key]["BuildingName"], key, "residential", aliases)
    return specs, missing


def main():
    inventory = json.loads((ROOT / "data/private/residence_floorplans/manifest.json").read_text())
    data = json.loads((ROOT / ".cache/residence-access.json").read_text())
    specs, missing = residence_specs(inventory["records"], data["buildings"])
    osm_paths = list((ROOT / ".cache/osm").glob("*.json"))
    osm = dict(elements=[])
    for path in osm_paths:
        payload = json.loads(path.read_text())
        osm["elements"].extend(payload.get("elements", []))
    xml_path = ROOT / ".cache/residence-map.osm"
    if xml_path.exists():
        for node in ET.parse(xml_path).getroot().findall("node"):
            tags = {t.attrib["k"]: t.attrib["v"] for t in node.findall("tag")}
            if tags.get("entrance") in ("yes", "main"):
                osm["elements"].append(
                    dict(
                        type="node",
                        id=int(node.attrib["id"]),
                        lat=float(node.attrib["lat"]),
                        lon=float(node.attrib["lon"]),
                        tags=tags,
                    )
                )
    # Duplicate cached Overpass nodes must not create duplicate entrance IDs.
    osm["elements"] = list({(r["type"], r["id"]): r for r in osm["elements"]}.values())
    catalog, assets = normalize(data, osm, datetime.now(UTC), building_specs=specs, bbox=BBOX)
    catalog["residence_inventory_unmatched"] = missing
    catalog["bbox"] = list(BBOX)
    graph_path = ROOT / "data/umass-residences.graph.json"
    if graph_path.exists():
        catalog = add_network_approaches(catalog, data, RoutingEngine.from_file(graph_path), specs)
    atomic_json(ROOT / "data/residence_buildings.json", catalog)
    atomic_json(ROOT / "data/residence_assets.json", assets)
    halls = [b for b in catalog["buildings"] if b["category"] == "residential"]
    print("Matched residences:", len(halls), "Unmatched plan records:", len(missing))
    print(
        "Entrances:",
        sum(len(b["entrances"]) for b in halls),
        "No entrances:",
        [b["name"] for b in halls if not b["entrances"]],
    )


if __name__ == "__main__":
    main()
