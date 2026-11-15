"""Run a request against any cached graph; print a GeoJSON feature to stdout."""

import argparse
from pathlib import Path

from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.models import RouteRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--graph", type=Path, default=Path("data/umass.graph.json"))
    args = parser.parse_args()
    request = RouteRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    try:
        response = RoutingEngine.from_file(args.graph).route(request)
    except (OSError, ValueError, RoutingError) as exc:
        parser.exit(1, f"Routing failed: {exc}\n")
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
