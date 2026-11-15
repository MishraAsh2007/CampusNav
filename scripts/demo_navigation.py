"""Offline guided-flow demo. The two layouts are fictional, never campus routing data."""

from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.engine import RoutingEngine
from campus_routing.indoor import IndoorMap
from campus_routing.navigation import ArrivalRequest, NavigationRequest, NavigationService
from campus_routing.places import PlaceResolver
from scripts.demo_indoor import NOW, demo_map, lift_closure
from scripts.make_demo import make_demo_graph

ROOT = Path(__file__).resolve().parents[1]


def pilot_fixtures():
    """Use pilot IDs for protocol tests, with synthetic names, sources and flags."""
    maps = {}
    for building, lat, outdoor_node in [("library", 42.392, 2), ("ilc", 42.391, 1)]:
        data = demo_map().model_dump(mode="json")
        data.update(building_id=building, name=f"SYNTHETIC {building} protocol fixture")
        for asset in data["assets"]:
            asset["id"] = asset["id"].replace("demo-", building + "-")
            asset["label"] = asset["id"]
            asset["position"]["lat"] = lat
        for edge in data["edges"]:
            if edge["asset_id"]:
                edge["asset_id"] = edge["asset_id"].replace("demo-", building + "-")
        for node in data["nodes"]:
            if node["position"]:
                node["position"]["lat"] = lat
            if node["kind"] == "elevator_stop":
                letter = node["id"][0].upper()
                node["label"] = f"Demo elevator {letter} landing"
                node["aliases"] = [f"elevator {letter}", f"lift {letter}"]
            if node["kind"] == "room":
                room = "N211" if building == "ilc" else "201"
                node["label"] = f"Demo room {room}"
                node["aliases"] = [room, f"room {room}"]
        data["portals"][0].update(
            id=f"{building}-entrance",
            outdoor_node_id=outdoor_node,
            geometry=[[-72.52805, lat], [-72.528, lat]],
        )
        data["maneuvers"] = [
            dict(
                id="demo-second-door",
                from_node="a2",
                via_node="hall2",
                to_node="room-201",
                instruction="Take the second classroom on your right: Demo room N211."
                if building == "ilc"
                else "Continue to the labeled Demo room 201.",
                source_id=data["sources"][0]["id"],
                evidence="Fictional directional cue for testing only. Not a real room position.",
            )
        ]
        maps[building] = IndoorMap.model_validate(data)
    return maps


def pilot_outage(building="ilc", lift="a"):
    return lift_closure(
        asset_id=f"{building}-lift-{lift}",
        building_id=building,
        lat=42.391 if building == "ilc" else 42.392,
    )


def main():
    service = NavigationService(
        RoutingEngine(make_demo_graph()),
        PlaceResolver(pilot_fixtures(), {}, allow_synthetic=True),
        lambda: ([], dict(stale=False)),
    )
    initial = NavigationRequest(
        origin=dict(text="second floor of the library"),
        destination=dict(text="ILC"),
    )
    clarify = service.plan(initial, now=NOW)
    start = initial.model_copy(
        update={"origin": initial.origin.model_copy(update={"node_id": "a2"})}
    )
    planned = service.plan(start, now=NOW)
    arrival = ArrivalRequest(**planned["arrival_context"], confirmed=True)
    prompt = service.arrive(arrival, now=NOW)
    finish = ArrivalRequest(
        **planned["arrival_context"],
        confirmed=True,
        continue_indoors=True,
        destination=dict(text="N211"),
        closures=[pilot_outage()],
    )
    inside = service.arrive(finish, now=NOW)
    for label, response in [
        ("Floor clarification", clarify),
        ("Trip to entrance", planned),
        ("Arrival question", prompt),
        ("Indoor detour", inside),
    ]:
        print(label + ":", response["status"])
    print(
        "Final elevator:",
        [
            t["asset_id"]
            for leg in inside["journey"]["legs"]
            if leg["kind"] == "indoor"
            for t in leg["transitions"]
        ],
    )
    folder = ROOT / "examples/navigation"
    for name, payload in [
        ("clarification", clarify),
        ("plan-request", start.model_dump(mode="json")),
        ("plan-response", planned),
        ("arrival-question", prompt),
        ("arrive-request", finish.model_dump(mode="json")),
        ("arrive-response", inside),
    ]:
        atomic_json(folder / (name + ".json"), payload)
    print("Synthetic layouts only. Written under examples/navigation; never production maps.")


if __name__ == "__main__":
    main()
