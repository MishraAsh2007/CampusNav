"""Exercise shortest, step-free, and elevator-outage routes without network access."""

import json
from datetime import UTC, datetime
from pathlib import Path

from campus_routing.engine import RoutingEngine
from campus_routing.graph import write_json
from campus_routing.models import RouteRequest


def main():
    engine = RoutingEngine.from_file("data/demo.graph.json")
    for name in ("standard", "accessible", "outage"):
        request = RouteRequest.model_validate_json(
            Path(f"examples/route-{name}.json").read_text(encoding="utf-8")
        )
        # Read the shared dummy closures file as the backend/UI would do.
        if name == "outage":
            closures = json.loads(Path("examples/closures.json").read_text(encoding="utf-8"))
            request = RouteRequest.model_validate({**request.model_dump(), "closures": closures})
        result = engine.route(request, now=datetime(2020, 1, 1, 1, tzinfo=UTC))
        write_json(Path(f"examples/response-{name}.geojson"), result.model_dump(mode="json"))
        p = result.properties
        print(
            f"{name:12s} {p.total_distance:7.2f} m | max grade {p.max_grade}% | "
            f"stairs={p.uses_stairs} | elevator={p.uses_elevator}"
        )


if __name__ == "__main__":
    main()
