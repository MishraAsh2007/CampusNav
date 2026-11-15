"""Audit every mapped pilot destination and floor, separately from physical verification."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.engine import RoutingError
from campus_routing.indoor import IndoorEngine, IndoorRouteRequest, read_indoor
from campus_routing.models import Closure

ROOT = Path(__file__).resolve().parents[1]


def audit_building(data):
    engine = IndoorEngine(data)
    entrances = [n for n in data.nodes if n.kind == "entrance"]
    results = []
    now = datetime.now(UTC)
    lifts = [a for a in data.assets if a.kind == "elevator"]
    scenarios = [(a.id, [a.id]) for a in lifts]
    if len(lifts) > 1:
        scenarios.append(("all_elevators", [a.id for a in lifts]))
    outages = []
    for scenario, asset_ids in scenarios:
        closures = [
            Closure(
                lat=0,
                lng=0,
                radius=1,
                type="elevator",
                status="closed",
                source="official",
                building_id=data.building_id,
                asset_id=asset_id,
                start_time=now - timedelta(minutes=1),
                end_time=now + timedelta(hours=1),
                last_confirmed=now,
            )
            for asset_id in asset_ids
        ]
        checks = []
        for room in (n for n in data.nodes if n.kind == "room"):
            feasible = False
            for entry in entrances:
                try:
                    route = engine.route(
                        IndoorRouteRequest(
                            building_id=data.building_id,
                            start_node_id=entry.id,
                            end_node_id=room.id,
                            closures=closures,
                        ),
                        now=now,
                    )
                    used = {t["asset_id"] for t in route["transitions"]}
                    if used.intersection(asset_ids):
                        raise AssertionError("Route used a closed elevator")
                    if any(s["kind"] == "steps" for s in route["steps"]):
                        raise AssertionError("Step-free route used stairs")
                    feasible = True
                    break
                except RoutingError as error:
                    if error.code != "no_indoor_route":
                        raise
            checks.append(dict(node_id=room.id, route_available=feasible))
        outages.append(dict(scenario=scenario, closed_asset_ids=asset_ids, destinations=checks))
    for floor in data.floors:
        rooms = [n for n in data.nodes if n.floor_id == floor.id and n.kind == "room"]
        checks = []
        for room in rooms:
            directions = []
            for reverse in (False, True):
                feasible = False
                for entry in entrances:
                    start, end = (room, entry) if reverse else (entry, room)
                    try:
                        engine.route(
                            IndoorRouteRequest(
                                building_id=data.building_id,
                                start_node_id=start.id,
                                end_node_id=end.id,
                            )
                        )
                        feasible = True
                        break
                    except RoutingError as error:
                        if error.code != "no_indoor_route":
                            raise
                directions.append(feasible)
            checks.append(
                dict(
                    node_id=room.id,
                    label=room.label,
                    reachable_from_entrance=directions[0],
                    can_return_to_entrance=directions[1],
                )
            )
        results.append(
            dict(
                floor_id=floor.id,
                label=floor.label,
                has_plan=bool(floor.image_url),
                room_count=len(rooms),
                destinations=checks,
                reachable_count=sum(c["reachable_from_entrance"] for c in checks),
                returnable_count=sum(c["can_return_to_entrance"] for c in checks),
                physical_verification="not_established_by_route_test",
            )
        )
    return dict(
        building_id=data.building_id,
        map_status=data.status,
        floors=results,
        source_notes=data.review_notes,
        elevator_outage_checks=outages,
        warning="Computable routes do not verify walls, doorways, scale, access or stops.",
    )


def main():
    results = [
        audit_building(read_indoor(ROOT / f"data/indoor/{b}.json")) for b in ("ilc", "library")
    ]
    payload = dict(buildings=results)
    workspace = ROOT / "data/private/residence_floorplans/workspaces/index.json"
    if workspace.exists():
        index = json.loads(workspace.read_text())
        payload["residences"] = dict(
            building_count=index["building_count"],
            floors=sum(b["floor_count"] for b in index["buildings"]),
            by_area=dict(Counter(b["area"] for b in index["buildings"])),
            reviewed_route_count=0,
            note="Workspace preparation does not publish routes.",
        )
    atomic_json(ROOT / "docs/indoor-coverage-audit.json", payload)
    lines = [
        "# Indoor floor and destination coverage audit",
        "",
        "Generated from current local map data. Routing success is a graph test; "
        "physical route verification is a separate requirement.",
        "",
        "| Building | Floor | Plan asset | Destinations | Reachable / returnable |",
        "| --- | --- | --- | --- | --- |",
    ]
    for building in results:
        for floor in building["floors"]:
            lines.append(
                f"| {building['building_id']} | {floor['label']} | "
                f"{'Yes' if floor['has_plan'] else 'Missing'} | {floor['room_count']} | "
                f"{floor['reachable_count']} / {floor['returnable_count']} |"
            )
        print(
            building["building_id"],
            len(building["floors"]),
            "floors;",
            sum(f["room_count"] for f in building["floors"]),
            "destinations; missing plans:",
            [f["floor_id"] for f in building["floors"] if not f["has_plan"]],
        )
    lines += [
        "",
        "See `indoor-coverage-audit.json` for each destination and source notes.",
        "A zero-destination floor is not complete room coverage. A plan asset does "
        "not establish that every route segment has been traced.",
        "",
    ]
    (ROOT / "docs/INDOOR_COVERAGE_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
