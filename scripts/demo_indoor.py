"""Offline two-floor indoor/outdoor demonstration. All geometry is synthetic."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.engine import RoutingEngine, RoutingError
from campus_routing.indoor import IndoorEngine, IndoorMap, IndoorRouteRequest
from campus_routing.journey import JourneyRequest, plan_journey
from campus_routing.models import Closure
from scripts.make_demo import make_demo_graph

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


def demo_map():
    source = "synthetic-fixture"
    nodes = []
    for floor in ("1", "2"):
        for key, x, kind in [
            ("hall", 2, "junction"),
            ("a", 5, "elevator_stop"),
            ("b", 15, "elevator_stop"),
        ]:
            nodes.append(
                dict(
                    id=key + floor,
                    label=key.upper() + " landing",
                    floor_id=floor,
                    kind=kind,
                    x=x,
                    y=0,
                    source_id=source,
                )
            )
    nodes.extend(
        [
            dict(
                id="entrance",
                label="Demo entrance",
                floor_id="1",
                kind="entrance",
                x=0,
                y=0,
                position=dict(lat=42.392, lng=-72.52805),
                source_id=source,
            ),
            dict(
                id="room-201",
                label="Demo room 201",
                floor_id="2",
                kind="room",
                x=0,
                y=0,
                source_id=source,
            ),
        ]
    )
    by_id = {n["id"]: n for n in nodes}
    edges = []

    def edge(ident, a, b, length, kind="corridor", asset=None, grade=0):
        left, right = by_id[a], by_id[b]
        edges.append(
            dict(
                id=ident,
                start=a,
                end=b,
                kind=kind,
                length_m=length,
                geometry=[[left["x"], left["y"]], [right["x"], right["y"]]]
                if left["floor_id"] == right["floor_id"]
                else None,
                asset_id=asset,
                public_access=True,
                step_free=kind != "steps",
                grade_percent=grade,
                width_m=1.5,
                door_type="automatic",
                source_id=source,
                evidence="Synthetic test layout; not a UMass building.",
            )
        )

    edge("entrance-hall", "entrance", "hall1", 2, asset="demo-hall")
    edge("hall-room", "hall2", "room-201", 2, asset="demo-hall")
    for floor in ("1", "2"):
        edge("hall-a" + floor, "hall" + floor, "a" + floor, 3)
        edge("hall-b" + floor, "hall" + floor, "b" + floor, 13)
    edge("lift-a", "a1", "a2", 4, "elevator", "demo-lift-a")
    edge("lift-b", "b1", "b2", 4, "elevator", "demo-lift-b")
    edge("stairs", "hall1", "hall2", 4, "steps", grade=50)
    return IndoorMap.model_validate(
        dict(
            building_id="demo-building",
            name="SYNTHETIC two-floor building",
            synthetic=True,
            status="reviewed",
            reviewed_at=NOW,
            review_notes="Test fixture review only; never a campus fact.",
            sources=[
                dict(
                    id=source,
                    url="https://example.org/synthetic-indoor-fixture",
                    edition="Synthetic",
                    observed_at=NOW,
                )
            ],
            floors=[dict(id=f, label="Floor " + f, source_id=source) for f in ("1", "2")],
            nodes=nodes,
            edges=edges,
            assets=[
                dict(
                    id=a,
                    label=a,
                    kind="elevator" if "lift" in a else "path",
                    source_id=source,
                    position=dict(lat=42.392, lng=-72.52805),
                )
                for a in ("demo-lift-a", "demo-lift-b", "demo-hall")
            ],
            portals=[
                dict(
                    id="demo-entrance-link",
                    indoor_node_id="entrance",
                    outdoor_node_id=2,
                    geometry=[[-72.52805, 42.392], [-72.528, 42.392]],
                    length_m=4.2,
                    public_access=True,
                    step_free=True,
                    grade_percent=0,
                    width_m=1.5,
                    door_type="automatic",
                    source_id=source,
                    evidence="Synthetic reviewed link to demo graph node 2; not campus access.",
                )
            ],
        )
    )


def lift_closure(asset_id="demo-lift-a", **updates):
    values = dict(
        lat=42.392,
        lng=-72.52805,
        radius=4,
        type="elevator",
        status="closed",
        source="community",
        start_time=NOW - timedelta(hours=1),
        end_time=NOW + timedelta(hours=24),
        last_confirmed=NOW,
        building_id="demo-building",
        asset_id=asset_id,
    )
    return Closure.model_validate({**values, **updates})


def main():
    folder = ROOT / "examples/indoor"
    data = demo_map()
    engine = IndoorEngine(data, allow_synthetic=True)
    req = IndoorRouteRequest(
        building_id=data.building_id, start_node_id="entrance", end_node_id="room-201"
    )
    baseline = engine.route(req, now=NOW)
    req.closures = [lift_closure()]
    rerouted = engine.route(req, now=NOW)
    outdoor = RoutingEngine(make_demo_graph())
    journey_req = JourneyRequest.model_validate(
        dict(
            origin=dict(kind="outdoor", lat=42.391, lng=-72.528),
            destination=dict(kind="indoor", building_id=data.building_id, node_id="room-201"),
            closures=[lift_closure().model_dump(mode="json")],
        )
    )
    journey = plan_journey(outdoor, lambda _: engine, journey_req, now=NOW)
    for name, payload in [
        ("demo-building.json", data.model_dump(mode="json")),
        ("baseline.json", baseline),
        ("elevator-outage.json", rerouted),
        ("journey-request.json", journey_req.model_dump(mode="json")),
        ("journey-response.json", journey),
    ]:
        atomic_json(folder / name, payload)
    for name, result in [("Baseline", baseline), ("Elevator A closed", rerouted)]:
        print(name, result["total_distance"], "m;", [t["asset_id"] for t in result["transitions"]])
    req.closures.append(lift_closure("demo-lift-b"))
    try:
        engine.route(req, now=NOW)
    except RoutingError as exc:
        print("Both elevators closed:", exc.code)
    print("Outdoor + portal + indoor:", [leg["kind"] for leg in journey["legs"]])
    print("All outputs are synthetic and written only under examples/indoor/.")


if __name__ == "__main__":
    main()
