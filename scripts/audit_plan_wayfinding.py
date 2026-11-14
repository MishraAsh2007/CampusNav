"""Exercise every landmark in each enabled drawing/landmark wayfinding pilot."""

from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.engine import RoutingError
from campus_routing.plan_wayfinding import PlanWayfindingMap, PlanWayfindingRequest, plan_directions

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "oak": "exit-threshold",
    "campus-center": "amherst-foyer",
    "student-union": "gallery-235",
}


def audit(data, target):
    results = []
    for node in data.nodes:
        answers = []
        for a, b in [(node.id, target), (target, node.id)]:
            try:
                response = plan_directions(
                    data,
                    PlanWayfindingRequest(
                        start_node_id=a,
                        end_node_id=b,
                        accept_drawing_only=True,
                        resident_access_confirmed=True,
                    ),
                )
                assert all(
                    s["geometry"] is None for s in response["steps"] if s["kind"] == "elevator"
                )
                answers.append(True)
            except RoutingError as error:
                if error.code != "no_plan_path":
                    raise
                answers.append(False)
        results.append(
            dict(
                node_id=node.id,
                floor_id=node.floor_id or data.floor_id,
                reachable=answers[0],
                returnable=answers[1],
            )
        )
    return dict(
        building_id=data.building_id,
        target=target,
        nodes=results,
        floors=sorted({r["floor_id"] for r in results}),
        physical_verification=False,
    )


def main():
    results = []
    for building, target in TARGETS.items():
        path = ROOT / "data/private/plan_wayfinding" / f"{building}.json"
        data = PlanWayfindingMap.model_validate_json(path.read_text())
        report = audit(data, target)
        results.append(report)
        print(
            building,
            len(data.nodes),
            "landmarks;",
            sum(r["reachable"] and r["returnable"] for r in report["nodes"]),
            "reachable to/from target",
        )
    atomic_json(ROOT / "data/private/plan_wayfinding/coverage-audit.json", dict(buildings=results))
    lines = [
        "# Expanded wayfinding coverage",
        "",
        "These are source-based graph checks, not physical accessibility verification.",
        "",
        "| Building | Floor | Landmarks | Reachable to/from audit target |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        for floor in result["floors"]:
            rows = [r for r in result["nodes"] if r["floor_id"] == floor]
            count = sum(r["reachable"] and r["returnable"] for r in rows)
            lines.append(f"| {result['building_id']} | {floor} | {len(rows)} | {count} |")
    lines += [
        "",
        "Oak target: exit-threshold. Campus Center target: amherst-foyer. "
        "Student Union target: gallery-235. Disconnected floors/areas can still "
        "have same-floor routes; they have no verified connecting link in this map.",
        "",
    ]
    (ROOT / "docs/EXPANDED_WAYFINDING_COVERAGE.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
