"""Generate contracts for Role 2 and Role 3 from the actual runtime models."""

from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.indoor import IndoorMap, IndoorRouteRequest
from campus_routing.journey import JourneyRequest
from campus_routing.models import Closure, RouteRequest
from campus_routing.navigation import ArrivalRequest, NavigationRequest
from campus_routing.places import ResolveRequest

ROOT = Path(__file__).resolve().parents[1]


def main():
    for name, model in (
        ("indoor-map", IndoorMap),
        ("indoor-route-request", IndoorRouteRequest),
        ("journey-request", JourneyRequest),
        ("navigation-request", NavigationRequest),
        ("arrival-request", ArrivalRequest),
        ("resolve-location-request", ResolveRequest),
        ("closure", Closure),
        ("route-request", RouteRequest),
    ):
        path = ROOT / "contracts" / (name + ".schema.json")
        atomic_json(path, model.model_json_schema())
        print(path.name)


if __name__ == "__main__":
    main()
