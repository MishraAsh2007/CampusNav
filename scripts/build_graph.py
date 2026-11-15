"""Download once, enrich once, route offline. Run from the repository root."""

import argparse
import math
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import osmnx as ox

from campus_routing.elevation import DEFAULT_ENDPOINT, fetch_elevations
from campus_routing.graph import save_graph

DEFAULT_BBOX = (-72.536, 42.3835, -72.519, 42.3955)  # west, south, east, north


def incline_percent(value):
    """OSM inclines may be percentages or degrees; up/down alone is unknown."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        if text.endswith("°"):
            degrees = abs(float(text[:-1]))
            return math.tan(math.radians(degrees)) * 100 if degrees < 90 else None
        result = abs(float(text.removesuffix("%")))
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def normalize(osm, elevations, *, bbox):
    graph = nx.MultiDiGraph(
        source="OpenStreetMap contributors",
        synthetic=False,
        attribution="© OpenStreetMap contributors, ODbL 1.0; https://www.openstreetmap.org/copyright",
        built_at=datetime.now(UTC).isoformat(),
        bbox=list(bbox),
        elevation_source=DEFAULT_ENDPOINT if elevations else None,
        grade_note="Absolute segment grade from OSM incline or terrain elevations; not surveyed.",
    )
    for node, data in osm.nodes(data=True):
        elevation = elevations.get((data["y"], data["x"]))
        graph.add_node(int(node), lat=float(data["y"]), lng=float(data["x"]), elevation=elevation)
    for u, v, key, data in osm.edges(keys=True, data=True):
        length = float(data["length"])
        if not math.isfinite(length) or length <= 0 or u == v:
            continue
        highway = data.get("highway", "path")
        if highway == "steps":
            kind = "steps"  # ramp=yes on stairs does not prove a separate wheelchair ramp exists.
        elif highway == "elevator":
            kind = "elevator"
        elif data.get("ramp") == "yes" or data.get("ramp:wheelchair") == "yes":
            kind = "ramp"
        else:
            kind = "path"
        grade = incline_percent(data.get("incline"))
        grade_source = "osm_incline" if grade is not None else None
        if kind == "elevator":
            grade, grade_source = 0, "elevator"  # Not a walking slope.
        elif grade is None:
            a, b = (graph.nodes[n]["elevation"] for n in (u, v))
            if a is not None and b is not None:
                grade, grade_source = abs(b - a) / length * 100, "dem"
        geometry = data.get("geometry")
        coords = (
            list(geometry.coords)
            if geometry is not None
            else [[graph.nodes[n]["lng"], graph.nodes[n]["lat"]] for n in (u, v)]
        )
        graph.add_edge(
            int(u),
            int(v),
            key=int(key),
            length=length,
            coordinates=coords,
            grade_percent=grade,
            grade_source=grade_source,
            kind=kind,
            name=data.get("name", ""),
            highway=highway,
            wheelchair=data.get("wheelchair"),
            access=data.get("access"),
            foot=data.get("foot"),
            osmid=data.get("osmid"),
        )
    graph.graph["elevator_point_count"] = sum(
        d.get("highway") == "elevator" for _, d in osm.nodes(data=True)
    )
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        default=DEFAULT_BBOX,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/umass.graph.json"))
    parser.add_argument(
        "--skip-elevation",
        action="store_true",
        help="Leave unknown grades null; explicit diagnostic mode only",
    )
    parser.add_argument("--overpass-url", default="https://overpass-api.de/api")
    args = parser.parse_args()
    west, south, east, north = args.bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        parser.error("bbox must be west south east north")
    ox.settings.use_cache = True
    ox.settings.cache_folder = ".cache/osm"
    ox.settings.requests_timeout = 90
    ox.settings.overpass_url = args.overpass_url
    ox.settings.log_console = True
    ox.settings.useful_tags_way = list(
        set(ox.settings.useful_tags_way)
        | {
            "incline",
            "wheelchair",
            "ramp",
            "ramp:wheelchair",
            "foot",
            "surface",
            "level",
        }
    )
    ox.settings.useful_tags_node = list(
        set(ox.settings.useful_tags_node)
        | {
            "highway",
            "wheelchair",
            "barrier",
            "entrance",
            "level",
        }
    )
    # Preserve original segments: simplification before grading can average away steep sections.
    osm = ox.graph_from_bbox(
        tuple(args.bbox),
        network_type="walk",
        simplify=False,
        retain_all=True,
        truncate_by_edge=False,
    )
    points = [(data["y"], data["x"]) for _, data in osm.nodes(data=True)]
    elevations = (
        {} if args.skip_elevation else fetch_elevations(points, Path(".cache/elevations.json"))
    )
    graph = normalize(osm, elevations, bbox=args.bbox)
    # Atomic replacement only after the entire build succeeds; never discard last known graph.
    save_graph(graph, args.output)
    counts = {
        kind: sum(d["kind"] == kind for *_, d in graph.edges(data=True))
        for kind in ("steps", "path", "ramp", "elevator")
    }
    unknown = sum(d["grade_percent"] is None for *_, d in graph.edges(data=True))
    print(f"Saved {args.output}: {len(graph)} nodes, {graph.number_of_edges()} edges")
    print(f"Edge types (both directions): {counts}; unknown grades: {unknown}")


if __name__ == "__main__":
    main()
