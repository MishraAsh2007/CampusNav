"""Check outdoor approaches for every dorm against the expanded walking graph."""

import json
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.buildings import TripRequest, plan_trip
from campus_routing.engine import RoutingEngine, RoutingError

ROOT = Path(__file__).resolve().parents[1]


def write_report(payload):
    lines = [
        "# Residence outdoor route coverage",
        "",
        "Test origin: Campus Center. Both outbound and return directions must pass. "
        "Closures were explicitly empty for this coverage test. These are computed "
        "network approaches, not physically verified door connections.",
        "",
        "| Residence | Destination | Walking comparison | No stairs, 5% | "
        "No stairs, 8.33% | Indoor |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["buildings"]:
        checks = row["checks"]

        def passes(grade, rows=checks):
            return all(c["status"] == "route_ready" for c in rows if c["max_grade"] == grade)

        walking = all(c.get("standard_route_available") for c in checks)
        endpoint = (
            "Network meeting point"
            if row["network_meeting_points"]
            else "Sourced entrance approach"
        )
        lines.append(
            f"| {row['name']} | "
            f"{endpoint} | "
            f"{'Yes' if walking else 'Unavailable'} | "
            f"{'Yes' if passes(5) else 'Unavailable'} | "
            f"{'Yes' if passes(8.33) else 'Unavailable'} | Not enabled |"
        )
    lines += [
        "",
        "Walking comparison can include stairs and excessive grades. It is not "
        "an accessible-route fallback. Indoor route geometry remains unfinished.",
        "",
    ]
    (ROOT / "docs/RESIDENCE_ROUTE_COVERAGE.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    engine = RoutingEngine.from_file(ROOT / "data/umass-residences.graph.json")
    catalog = json.loads((ROOT / "data/residence_buildings.json").read_text())
    origin = next(b for b in catalog["buildings"] if b["id"] == "campus-center")
    results = []
    for building in catalog["buildings"]:
        if building["category"] != "residential":
            continue
        row = dict(
            building_id=building["id"],
            name=building["name"],
            sourced_entrances=sum(not e.get("approach_only") for e in building["entrances"]),
            network_meeting_points=sum(bool(e.get("approach_only")) for e in building["entrances"]),
            indoor_status="not_enabled",
            checks=[],
        )
        for max_grade in (5, 8.33):
            for reverse in (False, True):
                a, b = (building, origin) if reverse else (origin, building)
                request = TripRequest(
                    origin=dict(**a["location"], building_id=a["id"]),
                    destination=dict(**b["location"], building_id=b["id"]),
                    no_stairs=True,
                    max_grade=max_grade,
                    allow_keycard_entrance_approach=True,
                    closures=[],
                )
                try:
                    result = plan_trip(engine, catalog, request)
                    route = result["accessible"]
                    row["checks"].append(
                        dict(
                            max_grade=max_grade,
                            direction="return" if reverse else "outbound",
                            status="route_ready" if route else "no_route",
                            distance=route.properties.total_distance if route else None,
                            failure=result["failure"],
                            standard_route_available=result["standard"] is not None,
                            entrance_id=(
                                result["start_entrance"]
                                if reverse
                                else result["end_entrance"] or {}
                            ).get("id")
                            if route
                            else None,
                            approach_gap_m=(
                                route.properties.start_snap_distance
                                if reverse
                                else route.properties.end_snap_distance
                            )
                            if route
                            else None,
                        )
                    )
                except RoutingError as error:
                    row["checks"].append(
                        dict(
                            max_grade=max_grade,
                            direction="return" if reverse else "outbound",
                            status=error.code,
                            message=error.message,
                        )
                    )
        results.append(row)
        print(
            building["name"],
            [(c["max_grade"], c["direction"], c["status"]) for c in row["checks"]],
            flush=True,
        )
    payload = dict(
        origin="campus-center",
        synthetic=False,
        closures="explicit_empty_test",
        graph_nodes=len(engine.graph),
        graph_edges=engine.graph.number_of_edges(),
        scope="Outdoor network approaches only; gaps to doors are not traced. "
        "No indoor permission, operating status or physical verification implied.",
        buildings=results,
    )
    atomic_json(ROOT / "data/residence_route_audit.json", payload)
    write_report(payload)


if __name__ == "__main__":
    main()
