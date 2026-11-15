"""Honors dorm pilot: shared hall outside Oak 233 -> elevator -> floor-1 exit.

Drawings establish the candidate connections. Current accessibility/operation is unknown.
"""

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_notices.plan_integrity import require_reviewed_source
from campus_routing.plan_wayfinding import (
    PlanWayfindingMap,
    PlanWayfindingRequest,
    plan_directions,
)
from scripts.build_brown_trace import _source_url

ROOT = Path(__file__).resolve().parents[1]
BANK = "umass-elevator-183"  # Existing sourced Oak elevator/bank ID; not a car count.
POINTS = [
    ("outside-233", "Shared hall outside Room 233", "2", 349, 334),
    ("hall-2-bend", "Shared hall bend near Room 233", "2", 349, 351),
    ("hall-2-bank", "Second-floor hall at the elevator bank", "2", 357, 358),
    ("elevator-2", "Second-floor central elevator landing", "2", 370, 359),
    ("elevator-1", "First-floor central elevator landing", "1", 370, 348),
    ("lobby-125", "First-floor lobby 125", "1", 380, 374),
    ("lobby-west", "West side of lobby 125", "1", 350, 374),
    ("exit-approach", "Lobby approach to the exterior doorway", "1", 339, 389),
    ("exit-threshold", "First-floor exterior doorway; geographic match pending", "1", 337, 406),
]


def build(sources):
    nodes = [dict(id=key, label=label, floor_id=f, x=x, y=y) for key, label, f, x, y in POINTS]
    pairs = [
        ("outside-233", "hall-2-bend", "corridor"),
        ("hall-2-bend", "hall-2-bank", "corridor"),
        ("hall-2-bank", "elevator-2", "corridor"),
        ("elevator-2", "elevator-1", "elevator"),
        ("elevator-1", "lobby-125", "corridor"),
        ("lobby-125", "lobby-west", "corridor"),
        ("lobby-west", "exit-approach", "corridor"),
        ("exit-approach", "exit-threshold", "door"),
    ]
    edges = []
    for a, b, kind in pairs:
        edges.append(
            dict(
                id=a + "--" + b,
                start=a,
                end=b,
                kind=kind,
                asset_id=BANK
                if kind == "elevator"
                else "oak-shared-hall-" + next(n["floor_id"] for n in nodes if n["id"] == a),
                evidence="Explicit shared-space path inspected on 707-01/707-02; no private "
                "room or apartment interior included. Final access/clearance unverified.",
                served_floor_evidence="Both floor-1 and floor-2 plans show the corresponding "
                "central double-shaft bank beside the main stair core. Only these two "
                "drawn landings are connected; current service is unconfirmed."
                if kind == "elevator"
                else None,
            )
        )
    return PlanWayfindingMap(
        building_id="oak",
        floor_sources=sources,
        source_url=sources["1"]["url"],
        source_sha256=sources["1"]["sha256"],
        drawing_review="Inspected shared hall outside Room 233, central bank on floors 1/2, "
        "lobby 125 and candidate exterior threshold. Floor drawings supply topology only. "
        "No physical accessibility, operating status, or geographic entrance alignment verified.",
        nodes=nodes,
        connections=edges,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", action="store_true")
    parser.add_argument("--start", default="outside-233")
    parser.add_argument("--end", default="exit-threshold")
    parser.add_argument("--accept-drawing-only", action="store_true")
    parser.add_argument("--resident-access-confirmed", action="store_true")
    parser.add_argument("--close-elevator", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data/private/residence_floorplans/manifest.json").read_text())
    sources = {}
    records = {}
    for floor in ["1", "2"]:
        record = next(r for r in manifest["records"] if r["name"] == f"707-0{floor}.pdf")
        digest = hashlib.sha256(Path(record["local_path"]).read_bytes()).hexdigest()
        require_reviewed_source(record["name"], digest)
        if digest != record["sha256"]:
            raise ValueError("Source changed; re-inspect drawing")
        sources[floor] = dict(url=_source_url(record["server_relative_url"]), sha256=digest)
        records[floor] = record
    data = build(sources)
    output = ROOT / "data/private/plan_wayfinding"
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "oak-pilot.json", data.model_dump(mode="json"))
    if not (output / "oak.json").exists():
        atomic_json(output / "oak.json", data.model_dump(mode="json"))
    for floor, record in records.items():
        background = base64.b64encode(Path(record["trace"]["rendered_path"]).read_bytes()).decode()
        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 792 612">',
            f'<image width="792" height="612" href="data:image/png;base64,{background}"/>',
        ]
        nodes = {n.id: n for n in data.nodes}
        for e in data.connections:
            a, b = nodes[e.start], nodes[e.end]
            if a.floor_id == b.floor_id == floor:
                svg.append(
                    f'<polyline points="{a.x},{a.y} {b.x},{b.y}" fill="none" '
                    'stroke="#c00060" stroke-width="1.5"/>'
                )
        for n in data.nodes:
            if n.floor_id == floor:
                svg.append(
                    f'<circle cx="{n.x}" cy="{n.y}" r="2" fill="#007fa0">'
                    f"<title>{html.escape(n.label)}</title></circle>"
                )
        svg.append(
            '<text x="10" y="15" fill="#c00060" font-size="9">'
            "DRAWING PILOT: starts in shared hall; elevator operation/access "
            "unverified.</text></svg>"
        )
        (output / f"oak-pilot-floor-{floor}.svg").write_text("\n".join(svg), encoding="utf-8")
    print("Created shared-space two-floor pilot:", output / "oak.json")
    if args.route:
        data = PlanWayfindingMap.model_validate_json(
            (output / "oak.json").read_text(encoding="utf-8")
        )
        from datetime import UTC, datetime, timedelta

        from campus_routing.engine import RoutingError
        from campus_routing.models import Closure

        now = datetime.now(UTC)
        closures = (
            [
                Closure(
                    lat=0,
                    lng=0,
                    radius=1,
                    type="elevator",
                    status="closed",
                    source="official",
                    asset_id=BANK,
                    building_id="oak",
                    start_time=now - timedelta(minutes=1),
                    end_time=now + timedelta(hours=1),
                    last_confirmed=now,
                )
            ]
            if args.close_elevator
            else []
        )
        try:
            result = plan_directions(
                data,
                PlanWayfindingRequest(
                    start_node_id=args.start,
                    end_node_id=args.end,
                    accept_drawing_only=args.accept_drawing_only,
                    resident_access_confirmed=args.resident_access_confirmed,
                    closures=closures,
                ),
            )
        except RoutingError as error:
            print(error.code + ": " + error.message)
            raise SystemExit(1) from error
        atomic_json(output / "oak-last-route.json", result)
        for step in result["steps"]:
            print(step["instruction"])


if __name__ == "__main__":
    main()
