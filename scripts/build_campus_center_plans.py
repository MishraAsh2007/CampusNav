"""Trace bounded Campus Center public foyers/concourse from linked plan images."""

import argparse
import hashlib
import json
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_notices.central_plans import fetch_images
from campus_notices.plan_integrity import require_reviewed_source
from campus_routing.plan_wayfinding import PlanWayfindingMap

ROOT = Path(__file__).resolve().parents[1]
ASSET = "umass-elevator-141"


def build(records, concourse_evidence=None):
    images = {r["id"]: r for r in records}
    nodes = []
    edges = []
    sources = {}

    def node(key, label, f, x, y):
        nodes.append(dict(id=key, label=label, floor_id=f, x=x, y=y))

    def edge(a, b, f):
        edges.append(
            dict(
                id=a + "--" + b,
                start=a,
                end=b,
                kind="corridor",
                asset_id="cc-shared-floor-" + f,
                evidence="Visible shared circulation/foyer in linked "
                "Campus Center image. Endpoint is outside the room; no threshold inferred.",
            )
        )

    for f, filename in [
        ("1", "first-floor.png"),
        ("2", "second-floor.jpg"),
        ("8", "eight-floor.jpg"),
        ("9", "eight-floor.jpg"),
        ("10", "ten-11-floor.jpg"),
        ("11", "ten-11-floor.jpg"),
    ]:
        r = images[filename]
        sources[f] = dict(
            url=r["url"],
            sha256=r["sha256"],
            coordinate_system="image_pixels",
            width=str(r["width"]),
            height=str(r["height"]),
        )
    # Explicit foyer stations: diagrams label the elevator bank on these five floors.
    routes = {
        "1": [
            ("elevator-1", "First-floor elevator foyer", 164, 382),
            ("bank-turn-1", "Foyer around the elevator bank", 164, 354),
            ("foyer-1", "First-floor shared foyer", 220, 360),
            ("near-163", "Foyer near Room 163", 250, 360),
            ("room-163-northwest", "Hall at northwest corner of Room 163", 260, 320),
            ("room-163-northeast", "Hall at northeast corner of Room 163", 358, 320),
            ("near-174", "East foyer near Room 174", 355, 360),
            ("near-168", "East foyer near Room 168", 355, 410),
        ],
        "8": [
            ("elevator-8", "Eighth-floor shared elevator foyer", 91, 283),
            ("foyer-8", "Eighth-floor central foyer", 91, 270),
            ("near-805", "Foyer near Room 805", 91, 236),
            ("near-803", "Foyer near Room 803", 91, 165),
            ("near-801", "Foyer near Room 801", 91, 111),
        ],
        "9": [
            ("elevator-9", "Ninth-floor shared elevator foyer", 414, 285),
            ("foyer-9", "Ninth-floor central foyer", 414, 270),
            ("near-905", "Foyer near Room 905", 414, 236),
            ("near-903", "Foyer near Room 903", 414, 165),
            ("near-901", "Foyer near Room 901", 414, 111),
        ],
        "10": [
            ("elevator-10", "Tenth-floor west elevator foyer", 49, 282),
            ("foyer-10", "Tenth-floor west foyer", 43, 350),
            ("amherst-foyer", "Foyer beside Amherst Room", 43, 393),
        ],
        "11": [
            ("elevator-11", "Eleventh-floor west elevator foyer", 340, 282),
            ("foyer-11", "Eleventh-floor west foyer", 335, 330),
            ("marriott-foyer", "Foyer beside Marriott Center", 335, 358),
        ],
    }
    for floor, points in routes.items():
        for key, label, x, y in points:
            node(key, label, floor, x, y)
        for a, b in zip(points, points[1:], strict=False):
            edge(a[0], b[0], floor)
    # Current concourse image has clear landmark approaches, but no unambiguous
    # elevator labeling: do not invent a cross-floor connection to it.
    for key, label, x, y in [
        ("west-entry-2", "West concourse entry approach", 190, 230),
        ("concourse-2", "Central public concourse", 350, 210),
        ("harvest-approach", "Concourse by Harvest Market", 460, 205),
        ("east-entry-2", "East concourse entry approach", 575, 230),
        ("u-pub-approach", "Concourse by U-Pub", 575, 190),
    ]:
        node(key, label, "2", x, y)
    for a, b in [
        ("west-entry-2", "concourse-2"),
        ("concourse-2", "harvest-approach"),
        ("harvest-approach", "east-entry-2"),
        ("east-entry-2", "u-pub-approach"),
    ]:
        edge(a, b, "2")
    if concourse_evidence:
        program = concourse_evidence["cc-2026-conference-program"]
        hotel = concourse_evidence["cc-hotel-directions"]
        require_reviewed_source("cc-2026-conference-program.pdf", program["sha256"])
        sources["2"].update(
            annotation_url=program["url"],
            annotation_sha256=program["sha256"],
            annotation_page="31 (printed page 30)",
            service_directions_url=hotel["url"],
            service_directions_sha256=hotel["sha256"],
        )
        node("bank-front-2", "Concourse in front of the labeled elevator core", "2", 331, 210)
        node("elevator-2", "Concourse elevator-bank approach; follow local signs", "2", 331, 225)
        edge("concourse-2", "bank-front-2", "2")
        edge("bank-front-2", "elevator-2", "2")
    floors = list(routes)
    if concourse_evidence:
        floors.insert(1, "2")
    for a, b in zip(floors, floors[1:], strict=False):
        edges.append(
            dict(
                id=f"cc-elevator-{a}-{b}",
                start="elevator-" + a,
                end="elevator-" + b,
                kind="elevator",
                asset_id=ASSET,
                evidence=(
                    "2026 conference plan page 31 labels the concourse elevator core and "
                    "11th-floor bank. Hotel UMass directs visitors from the concourse "
                    "upstairs via elevators. Documentary alignment to the modeled bank."
                    if "2" in (a, b)
                    else "Elevator bank is labeled in both source-floor diagrams."
                ),
                served_floor_evidence=f"Linked Campus Center plans explicitly mark elevator foyers "
                f"on floors {a} and {b}; operation and car identity are unconfirmed. "
                "No stop on omitted floors is inferred. Floor-2 coordinates locate the "
                "approach outside the core, not an exact car door.",
            )
        )
    return PlanWayfindingMap(
        building_id="campus-center",
        coordinate_system="image_pixels",
        resident_access_required=False,
        source_url=sources["1"]["url"],
        source_sha256=sources["1"]["sha256"],
        floor_sources=sources,
        nodes=nodes,
        connections=edges,
        drawing_review="Inspected bounded shared foyer stations on five event floors and "
        "concourse landmarks on floor 2. No event-room interiors or unshown doorway geometry.",
        source_warnings=[
            "Plans are currently linked by Hospitality but have no stated revision date.",
            (
                "Floor-2 bank approach is supported by a 2026 annotated conference plan and "
                "Hotel UMass directions; exact car doors and physical access are unverified."
                if concourse_evidence
                else "Floor 2 remains separate: elevator landing alignment is unresolved."
            ),
            "Coverage is selected foyers, not the entire Campus Center.",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    folder = ROOT / ".cache/central-plans"
    records = (
        fetch_images(folder)
        if args.refresh
        else json.loads((folder / "image-manifest.json").read_text())["records"]
    )
    manifest = ROOT / ".cache/central-plans/source-manifest.json"
    evidence = {}
    if manifest.exists():
        evidence = {
            r["id"]: r
            for r in json.loads(manifest.read_text())["records"]
            if r["id"] in ("cc-2026-conference-program", "cc-hotel-directions")
        }
    if len(evidence) == 2:
        for row in evidence.values():
            if hashlib.sha256(Path(row["local_path"]).read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Concourse source cache changed; refresh/review before tracing")
    else:
        evidence = None
    data = build(records, evidence)
    for row in records:
        if row["id"] == "student-union.jpg":
            continue
        digest = hashlib.sha256(Path(row["local_path"]).read_bytes()).hexdigest()
        require_reviewed_source(row["id"], digest)
    atomic_json(
        ROOT / "data/private/plan_wayfinding/campus-center.json", data.model_dump(mode="json")
    )
    print("Campus Center:", len(data.nodes), "landmarks;", len(data.connections), "connections")


if __name__ == "__main__":
    main()
