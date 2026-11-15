"""CLI: run standard vs. accessible routing against a mock request / closures file.

    python scripts/demo_route.py                                   # no closures
    python scripts/demo_route.py --closures mocks/closures.json    # with closures
    python scripts/demo_route.py --max-grade 8 --geojson out.geojson

Prints a comparison and (optionally) writes both routes as one GeoJSON FeatureCollection
that can be pasted into geojson.io or loaded by the frontend.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.graph.load import load_graph  # noqa: E402
from app.routing.pathfinding import plan_routes  # noqa: E402
from app.schemas import RouteRequest, RouteResult  # noqa: E402


def _print_route(label: str, r: RouteResult) -> None:
    print(f"\n=== {label} ({r.mode}) ===")
    if not r.found:
        print(f"  NO ROUTE: {r.reason}")
        return
    print(
        f"  {r.distance_m:.0f} m (~{r.duration_s / 60:.1f} min) | max grade {r.max_grade_pct:.1f}% | "
        f"stairs {r.steps_length_m:.0f} m | step-free: {r.is_step_free}"
    )
    for i, s in enumerate(r.segments, 1):
        print(f"  {i:>2}. {s.instruction}")
    for c in r.closures_applied:
        print(f"  closure {c.id} [{c.type.value}] blocked {c.edges_blocked} edge(s)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--request", type=Path, default=config.MOCKS_DIR / "sample_request.json")
    p.add_argument("--closures", type=Path, help="JSON file with a list of closures (overrides request)")
    p.add_argument("--max-grade", type=float, help="override max grade percent")
    p.add_argument("--geojson", type=Path, help="write both routes to this GeoJSON file")
    args = p.parse_args()

    body = json.loads(args.request.read_text(encoding="utf-8"))
    if args.closures:
        body["closures"] = json.loads(args.closures.read_text(encoding="utf-8"))
    if args.max_grade is not None:
        body["max_grade_pct"] = args.max_grade
    req = RouteRequest.model_validate(body)

    G = load_graph()
    resp = plan_routes(G, req)

    print(f"graph: {resp.meta.graph_nodes} nodes / {resp.meta.graph_edges} edges | "
          f"closures active={resp.meta.closures_active} expired={resp.meta.closures_expired} | "
          f"compute {resp.meta.compute_ms} ms")
    if resp.standard:
        _print_route("STANDARD (shortest)", resp.standard)
    _print_route("ACCESSIBLE", resp.accessible)

    if resp.destination:
        d = resp.destination
        ev = d.elevators
        print(f"\n=== DESTINATION: {d.building_name} ===")
        print(f"  entrance: {d.entrance.name if d.entrance else 'none usable'} | elevators working "
              f"{ev.working}/{ev.total} | upper floors reachable: {d.upper_floors_reachable}")
        for e in d.entrances:
            mark = "*" if e.chosen else " "
            print(f"  {mark} {e.name}: usable={e.usable} route={e.route_distance_m} m {'; '.join(e.reasons)}")
        for w in d.warnings:
            print(f"  ! {w}")

    if resp.standard and resp.standard.found and resp.accessible.found:
        same = resp.standard.geometry == resp.accessible.geometry
        print(f"\nroutes identical: {same}")

    if args.geojson:
        feats = []
        for r in (resp.standard, resp.accessible):
            if r and r.found:
                f = dict(r.geometry)
                f["properties"] = {"mode": r.mode, "distance_m": r.distance_m, "stroke": "#d33" if r.mode == "standard" else "#27a"}
                feats.append(f)
        args.geojson.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
        print(f"wrote {args.geojson}")


if __name__ == "__main__":
    main()
