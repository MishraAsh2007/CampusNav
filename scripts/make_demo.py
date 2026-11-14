"""Deterministic synthetic fixtures, deliberately separate from real OSM data."""

from pathlib import Path

import networkx as nx
from pyproj import Geod

from campus_routing.graph import save_graph, write_json
from campus_routing.models import Closure, RouteRequest, RouteResponse

GEOD = Geod(ellps="WGS84")


def make_demo_graph():
    graph = nx.MultiDiGraph(source="synthetic-demo", synthetic=True)
    points = {
        1: (42.3910, -72.5280),
        2: (42.3920, -72.5280),
        3: (42.3910, -72.5276),
        4: (42.39140, -72.5276),
        5: (42.39145, -72.5276),
        6: (42.3920, -72.5276),
        7: (42.3910, -72.5288),
        8: (42.3920, -72.5288),
    }
    for node, (lat, lng) in points.items():
        graph.add_node(node, lat=lat, lng=lng)
    segments = [
        (1, 2, "steps", 20, "Demo stairs"),
        (1, 3, "path", 2, "Demo east approach"),
        (3, 4, "path", 2, "Demo east approach"),
        (4, 5, "elevator", 0, "Demo elevator"),
        (5, 6, "path", 2, "Demo east approach"),
        (6, 2, "path", 2, "Demo east approach"),
        (1, 7, "ramp", 4, "Demo west detour"),
        (7, 8, "path", 3, "Demo west detour"),
        (8, 2, "ramp", 4, "Demo west detour"),
    ]
    for u, v, kind, grade, name in segments:
        lat1, lng1 = points[u]
        lat2, lng2 = points[v]
        length = GEOD.inv(lng1, lat1, lng2, lat2)[2]
        coords = [[lng1, lat1], [lng2, lat2]]
        for a, b, geometry in ((u, v, coords), (v, u, coords[::-1])):
            graph.add_edge(
                a,
                b,
                length=length,
                kind=kind,
                grade_percent=grade,
                grade_source="synthetic",
                name=name,
                coordinates=geometry,
            )
    return graph


def main():
    save_graph(make_demo_graph(), Path("data/demo.graph.json"))
    request = {
        "start": {"lat": 42.3910, "lng": -72.5280},
        "end": {"lat": 42.3920, "lng": -72.5280},
        "max_grade": 5,
        "no_stairs": True,
        "closures": [],
    }
    closure = {
        "lat": 42.391425,
        "lng": -72.5276,
        "radius": 8,
        "type": "elevator",
        "status": "closed",
        "source": "community",
        "start_time": "2020-01-01T00:00:00Z",
        "end_time": None,
        "last_confirmed": "2020-01-01T00:00:00Z",
    }
    write_json(Path("examples/closures.json"), [closure])
    write_json(Path("examples/route-accessible.json"), request)
    write_json(
        Path("examples/route-standard.json"),
        {
            **request,
            "max_grade": None,
            "no_stairs": False,
        },
    )
    write_json(Path("examples/route-outage.json"), {**request, "closures": [closure]})
    for name, model in (
        ("closure", Closure),
        ("route-request", RouteRequest),
        ("route-response", RouteResponse),
    ):
        write_json(Path(f"contracts/{name}.schema.json"), model.model_json_schema())
    print("Wrote synthetic graph, mock requests, dummy closures, and JSON schemas.")


if __name__ == "__main__":
    main()
