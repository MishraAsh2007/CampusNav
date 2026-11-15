"""Extend the offline walking graph with an OSM map extract without discarding it."""

import argparse
from pathlib import Path

import httpx
import osmnx as ox
from build_graph import normalize

from campus_routing.elevation import fetch_elevations
from campus_routing.graph import load_graph, save_graph

ROOT = Path(__file__).resolve().parents[1]
OSM_MAP_URL = "https://api.openstreetmap.org/api/0.6/map"


def fetch_osm_map(bbox, destination: Path):
    response = httpx.get(
        OSM_MAP_URL,
        params={"bbox": ",".join(str(value) for value in bbox)},
        timeout=120,
    )
    response.raise_for_status()
    if not response.content.startswith(b"<?xml"):
        raise ValueError("OSM map endpoint returned an unexpected response")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def extend_graph(existing_path: Path, output_path: Path, bbox, *, skip_elevation=False):
    osm_path = ROOT / ".cache" / "osm" / (
        "extension-" + "-".join(str(value).replace(".", "_") for value in bbox) + ".osm"
    )
    if not osm_path.exists():
        fetch_osm_map(bbox, osm_path)
    ox.settings.useful_tags_way = list(
        set(ox.settings.useful_tags_way)
        | {"incline", "wheelchair", "ramp", "ramp:wheelchair", "foot", "surface", "level"}
    )
    ox.settings.useful_tags_node = list(
        set(ox.settings.useful_tags_node)
        | {"highway", "wheelchair", "barrier", "entrance", "level"}
    )
    osm = ox.graph_from_xml(
        str(osm_path),
        simplify=False,
        retain_all=True,
    )
    points = [(data["y"], data["x"]) for _, data in osm.nodes(data=True)]
    elevations = (
        {}
        if skip_elevation
        else fetch_elevations(points, ROOT / ".cache" / "elevations.json")
    )
    addition = normalize(osm, elevations, bbox=bbox)
    graph = load_graph(existing_path)
    for node, data in addition.nodes(data=True):
        if node not in graph:
            graph.add_node(node, **data)
        else:
            graph.nodes[node].update(
                {key: value for key, value in data.items() if value is not None}
            )
    for start, end, data in addition.edges(data=True):
        graph.add_edge(start, end, **data)
    old_bbox = graph.graph.get("bbox", bbox)
    graph.graph["bbox"] = [
        min(old_bbox[0], bbox[0]),
        min(old_bbox[1], bbox[1]),
        max(old_bbox[2], bbox[2]),
        max(old_bbox[3], bbox[3]),
    ]
    graph.graph["extension_bbox"] = list(bbox)
    graph.graph["extension_source"] = (
        "OpenStreetMap map API extract; © OpenStreetMap contributors, ODbL 1.0"
    )
    graph.graph["elevator_point_count"] = sum(
        data.get("highway") == "elevator" for _, data in graph.nodes(data=True)
    )
    save_graph(graph, output_path)
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing", type=Path, default=ROOT / "data/umass.graph.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/private/brown-extended.graph.json",
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        default=(-72.536, 42.3950, -72.519, 42.3985),
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
    )
    parser.add_argument("--skip-elevation", action="store_true")
    args = parser.parse_args()
    graph = extend_graph(
        args.existing,
        args.output,
        tuple(args.bbox),
        skip_elevation=args.skip_elevation,
    )
    print(f"Saved {args.output}: {len(graph)} nodes, {graph.number_of_edges()} edges")


if __name__ == "__main__":
    main()
