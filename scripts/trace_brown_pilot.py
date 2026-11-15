"""Trace a small Brown first-floor suite/lobby/exit draft from the inspected drawing.

Drawing-derived lengths are estimates. This private draft is never marked reviewed.
"""

import base64
import hashlib
import html
import json
import math
from pathlib import Path

import networkx as nx

from campus_notices.cache import atomic_json
from campus_routing.indoor import IndoorMap

ROOT = Path(__file__).resolve().parents[1]

# PDF points read from the actual dimension strokes, not the room-label centers.
DIMENSIONS = [
    dict(label="10 feet", a=[286.873291, 213.226990], b=[318.119110, 212.709808], meters=3.048),
    dict(label="15 feet", a=[348.831299, 327.229004], b=[394.167297, 327.045990], meters=4.572),
    dict(
        label="10 feet 4 inches",
        a=[248.302704, 258.440308],
        b=[248.422699, 288.229309],
        meters=3.1496,
    ),
]

# Explicit doorway/junction positions, not projections onto a common corridor.
NODES = [
    ("room-107d-threshold", "Room 107D threshold", "room", 303, 278.7),
    ("suite-north-passage", "Suite 107 shared passage", "junction", 303, 286),
    ("suite-west-passage", "Suite 107 passage bend", "junction", 291, 286),
    ("suite-107-door", "Suite 107 exit doorway", "junction", 291, 311.5),
    ("hall-suite-107", "Main hall outside Suite 107", "junction", 291, 326),
    ("hall-lobby-approach", "Hall approach to lobby door", "junction", 287, 337),
    ("lobby-door", "Lobby double doorway", "junction", 285, 344.5),
    ("lobby-center", "First-floor lobby junction", "junction", 270, 357),
    ("west-shaft-approach", "Lobby approach to western shaft", "junction", 224, 351),
    ("lobby-south", "South side of first-floor lobby", "junction", 270, 390),
    ("vestibule-approach", "Approach to exit vestibule", "junction", 239, 399),
    ("vestibule-inner-door", "Inner vestibule doorway", "junction", 239, 412),
    ("vestibule-center", "Exit vestibule", "junction", 239, 425),
    # No geographic entrance/portal binding is claimed; this remains a floor-local junction.
    (
        "exterior-door-threshold",
        "Exterior doorway threshold; map alignment pending",
        "junction",
        239,
        436,
    ),
]
LINKS = [
    ("room-107d-threshold", "suite-north-passage", "door"),
    ("suite-north-passage", "suite-west-passage", "corridor"),
    ("suite-west-passage", "suite-107-door", "corridor"),
    ("suite-107-door", "hall-suite-107", "door"),
    ("hall-suite-107", "hall-lobby-approach", "corridor"),
    ("hall-lobby-approach", "lobby-door", "corridor"),
    ("lobby-door", "lobby-center", "door"),
    ("lobby-center", "west-shaft-approach", "corridor"),
    ("lobby-center", "lobby-south", "corridor"),
    ("lobby-south", "vestibule-approach", "corridor"),
    ("vestibule-approach", "vestibule-inner-door", "corridor"),
    ("vestibule-inner-door", "vestibule-center", "door"),
    ("vestibule-center", "exterior-door-threshold", "door"),
]


def build(source):
    factors = [d["meters"] / math.dist(d["a"], d["b"]) for d in DIMENSIONS]
    scale = sum(factors) / len(factors)
    spread = max(factors) / min(factors) - 1
    sid = source["id"]
    nodes = [
        dict(id=key, label=label, floor_id="1", kind=kind, x=x, y=y, source_id=sid)
        for key, label, kind, x, y in NODES
    ]
    positions = {n["id"]: (n["x"], n["y"]) for n in nodes}
    edges = []
    for start, end, kind in LINKS:
        edges.append(
            dict(
                id=start + "--" + end,
                start=start,
                end=end,
                kind=kind,
                length_m=round(math.dist(positions[start], positions[end]) * scale, 3),
                geometry=[positions[start], positions[end]],
                asset_id="brown-pilot-circulation",
                public_access=False,
                step_free=None,
                grade_percent=None,
                source_id=sid,
                evidence="Inspected floor-1 drawing polyline; length estimated from three "
                "dimension strokes. Drawing is Not To Scale and calibration varies by axis. "
                "Access, threshold clearance and grade are unknown. Private draft only.",
            )
        )
    data = IndoorMap.model_validate(
        dict(
            building_id="brown-house",
            name="Brown House first-floor trace pilot",
            status="draft",
            sources=[source],
            floors=[
                dict(
                    id="1",
                    label="First floor",
                    source_id=sid,
                    coordinate_system="image_pixels",
                    image_width=792,
                    image_height=612,
                )
            ],
            nodes=nodes,
            edges=edges,
            assets=[
                dict(
                    id="brown-pilot-circulation",
                    kind="path",
                    label="Brown pilot circulation",
                    source_id=sid,
                )
            ],
            review_notes="Private inspected drawing trace. PDF-point coordinates occupy the "
            "792x612 drawing space. Estimated distances are not surveyed. No elevator ride, "
            "geographic portal, resident authorization or verified step-free route is claimed.",
        )
    )
    # Test only connectivity of the drawing trace. This is not a production route response.
    graph = nx.Graph()
    for edge in data.edges:
        graph.add_edge(edge.start, edge.end, weight=edge.length_m)
    path = nx.shortest_path(
        graph, "room-107d-threshold", "exterior-door-threshold", weight="weight"
    )
    review = dict(
        coordinate_units="pdf_points",
        dimensions=DIMENSIONS,
        scale_estimates=factors,
        provisional_meters_per_point=scale,
        scale_spread_percent=round(spread * 100, 2),
        calibration_status="approximate_only_not_to_scale_drawing",
        traced_path=path,
        estimated_distance_m=round(nx.path_weight(graph, path, "weight"), 2),
        routing_eligible=False,
        blockers=[
            "Confirm suite and lobby door positions on site or in facilities plans",
            "Confirm access permissions, threshold clearance, walking grades and widths",
            "Verify metric lengths; dimension calibrations disagree",
            "Identify actual elevator shaft, door and documented served floors",
            "Align the exterior doorway with the geographic entrance and outdoor approach",
        ],
    )
    return data, review


def main():
    folder = ROOT / "data/private/residence_floorplans/workspaces/brown-house"
    evidence = json.loads((folder / "evidence.json").read_text())
    plan = next(p for p in evidence["plans"] if p["name"] == "426-01.pdf")
    manifest = json.loads((ROOT / "data/private/residence_floorplans/manifest.json").read_text())
    record = next(r for r in manifest["records"] if r["name"] == "426-01.pdf")
    if hashlib.sha256(Path(record["local_path"]).read_bytes()).hexdigest() != plan["sha256"]:
        raise ValueError("Source drawing changed; inspect before retracing")
    from scripts.build_brown_trace import _source_url

    source = dict(
        id=plan["source_id"],
        url=_source_url(record["server_relative_url"]),
        edition="426-01; drawing revision August 21, 2026",
        observed_at=evidence["observed_at"],
    )
    data, review = build(source)
    out = folder / "first-floor-pilot"
    atomic_json(out / "map.json", data.model_dump(mode="json"))
    atomic_json(out / "review.json", review)
    background = base64.b64encode(Path(plan["pages"][0]["rendered_path"]).read_bytes()).decode()
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 792 612">',
        f'<image width="792" height="612" href="data:image/png;base64,{background}"/>',
    ]
    for edge in data.edges:
        points = " ".join(f"{x},{y}" for x, y in edge.geometry)
        svg.append(f'<polyline points="{points}" fill="none" stroke="#c00060" stroke-width="1.5"/>')
    for node in data.nodes:
        svg.append(
            f'<circle cx="{node.x}" cy="{node.y}" r="2" fill="#006fa6">'
            f"<title>{html.escape(node.label)}</title></circle>"
        )
    svg += [
        '<rect x="5" y="5" width="782" height="16" fill="white"/>',
        '<text x="10" y="16" font-size="9" fill="#c00060">'
        "DRAFT DRAWING TRACE: estimated lengths; access, elevator stops and portal unverified."
        "</text></svg>",
    ]
    (out / "review.svg").write_text("\n".join(svg), encoding="utf-8")
    print("Private draft:", out / "map.json")
    print("Nodes/edges:", len(data.nodes), len(data.edges))
    print("Dimension calibration spread:", review["scale_spread_percent"], "percent")
    print("Estimated drawing path:", review["estimated_distance_m"], "m; not verified navigation")


if __name__ == "__main__":
    main()
