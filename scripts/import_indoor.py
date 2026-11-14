"""Validate reviewed indoor topology and atomically install it for the routing API."""

import argparse
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.graph import load_graph
from campus_routing.indoor import read_indoor

ROOT = Path(__file__).resolve().parents[1]


def import_map(source, output_dir, outdoor_path):
    data = read_indoor(source)
    if data.status != "reviewed" or data.synthetic:
        raise ValueError("Production imports require reviewed, non-synthetic topology")
    if data.portals:
        from pyproj import Geod

        graph = load_graph(outdoor_path)
        geod = Geod(ellps="WGS84")
        for portal in data.portals:
            if portal.outdoor_node_id not in graph:
                raise ValueError("Portal node is missing from the outdoor graph")
            node = graph.nodes[portal.outdoor_node_id]
            x, y = portal.geometry[-1]
            if geod.inv(x, y, node["lng"], node["lat"])[2] > 1:
                raise ValueError("Portal geometry does not reach its declared outdoor node")
    path = output_dir / (data.building_id + ".json")
    atomic_json(path, data.model_dump(mode="json"))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/indoor")
    parser.add_argument("--outdoor-graph", type=Path, default=ROOT / "data/umass.graph.json")
    args = parser.parse_args()
    print(import_map(args.source, args.output_dir, args.outdoor_graph))


if __name__ == "__main__":
    main()
