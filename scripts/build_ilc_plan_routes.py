"""Build the ILC 1-2 drawing pilot in original ArcGIS mosaic pixel coordinates.

These are corridor/doorway approaches, not surveyed accessible paths. Public
plans plus user-confirmed elevator identities support the drawing pilot only.
"""

import hashlib
import json
import shutil
from pathlib import Path

from campus_notices.plan_integrity import require_reviewed_source
from campus_routing.plan_wayfinding import PlanWayfindingMap
from scripts.ash_ilc_additions import add_routes, update_display_trace

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / "data/private/ilc-plan-audit"
    output = ROOT / "data/plan_wayfinding"
    images = output / "sources/ilc"
    images.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source = images  # Rebuild from the checked-in, fingerprinted source edition.
    floors = {}
    for floor in ("1", "2"):
        raw = (source / f"floor-{floor}.png").read_bytes()
        require_reviewed_source(f"ilc-floor-{floor}.png", hashlib.sha256(raw).hexdigest())
        meta = json.loads((source / f"floor-{floor}.json").read_text())
        target = images / f"floor-{floor}.png"
        if source.resolve() != images.resolve():
            shutil.copyfile(source / f"floor-{floor}.png", target)
            shutil.copyfile(source / f"floor-{floor}.json", images / f"floor-{floor}.json")
        floors[floor] = dict(
            local_image=target.relative_to(ROOT).as_posix(),
            source_url=meta["source_url"],
            source_sha256=hashlib.sha256(raw).hexdigest(),
            width="1536",
            height="1280",
            route_overlay="original_mosaic_pixels",
            extent=json.dumps(meta["extent"]),
        )
    nodes, connections = [], []

    def node(ident, floor, label, x, y):
        kind = (
            "entrance"
            if "entrance" in ident
            else "elevator_stop"
            if "-lift-" in ident
            else "room"
            if "-door-" in ident
            else "junction"
        )
        nodes.append(dict(id=ident, floor_id=str(floor), label=label, x=x, y=y, kind=kind))
        return ident

    def link(a, b, kind="corridor", asset=None, evidence=None):
        by_id = {n["id"]: n for n in nodes}
        ident = f"{a}--{b}"
        edge = dict(
            id=ident,
            start=a,
            end=b,
            kind=kind,
            asset_id=asset or ident,
            evidence=evidence
            or ("Hallway traced on original UMass ArcGIS mosaic; "
                "physical clearance unverified."),
        )
        if kind == "elevator":
            edge["served_floor_evidence"] = evidence
            for direction, start, end in [("forward", a, b), ("reverse", b, a)]:
                edge[f"{direction}_instruction"] = (
                    f"Take {by_id[start]['label']} to floor {by_id[end]['floor_id']}. "
                    "Confirm the floor sign before continuing."
                )
        connections.append(edge)

    # Every bend is an explicit node: no straight shortcut across an auditorium.
    corridors = {
        1: [
            ("north", "North lobby beside N155", 502, 440),
            ("north-bend", "North lobby corner", 485, 475),
            ("foyer", "Open foyer beside N151", 510, 590),
            ("foyer-south", "South end of the foyer", 552, 685),
            ("north-junction", "Hall junction above N111", 595, 721),
            ("west-core", "Hall beside the restrooms", 643, 737),
            ("west-hall", "Hall beside N111", 655, 802),
            ("south-junction", "Hall junction below N111", 665, 866),
            ("lift-lobby", "Elevator lobby opposite S140 / S142", 727, 861),
            ("south-hall", "Hall beside S120", 804, 853),
            ("east-hall", "Hall toward S110", 970, 843),
        ],
        2: [
            ("north", "North lobby beside N255", 500, 443),
            ("north-bend", "Hall west of the auditorium", 445, 493),
            ("foyer", "Hall beside N151 upper level", 465, 586),
            ("foyer-south", "Hall bend beside N151 upper level", 495, 675),
            ("north-junction", "Hall junction above N211", 551, 716),
            ("west-core", "Hall beside the restrooms", 610, 711),
            ("west-hall", "Hall beside N211", 625, 794),
            ("south-junction", "Open lobby below N211", 642, 875),
            ("lift-lobby", "Central elevator lobby on floor 2", 719, 861),
            ("south-hall", "Hall above S240", 803, 850),
            ("east-hall", "Hall toward S220", 968, 828),
        ],
    }
    for floor, points in corridors.items():
        previous = None
        for key, label, x, y in points:
            current = node(f"ilc-{key}-f{floor}", floor, label, x, y)
            if previous:
                link(previous, current)
            previous = current

    for floor, stops in {
        1: [("north", 512, 419), ("central-q", 716, 848), ("central-p", 740, 844)],
        2: [("north", 511, 416), ("central-q", 706, 846), ("central-p", 730, 842)],
    }.items():
        for key, x, y in stops:
            # Each landing names the room on that floor. Approaches and elevator
            # rides both use this label, including reverse (downstairs) routes.
            landmark = {
                "north": {1: "N155", 2: "N255"},
                "central-q": {1: "S187", 2: "S281"},
                "central-p": {1: "S131", 2: "S231"},
            }[key][floor]
            label = (
                f"North elevator beside {landmark}"
                if key == "north"
                else f"Central elevator nearest {landmark}"
            )
            ident = node(f"ilc-lift-{key}-f{floor}", floor, label, x, y)
            link(f"ilc-{'north' if key == 'north' else 'lift-lobby'}-f{floor}", ident)
    for key in ("north", "central-q", "central-p"):
        link(
            f"ilc-lift-{key}-f1",
            f"ilc-lift-{key}-f2",
            "elevator",
            f"ilc-lift-{key}",
            ("Matching shaft/landing symbols on both plans; user confirms north shaft "
             "and separate central pair. Current service is unverified."),
        )

    # Destinations stop in the hallway at the visible door, not inside tiered rooms.
    rooms = [
        (1, "n155", "N155 doorway", 548, 442, "north"),
        (1, "n111", "N111 north doorway", 525, 751, "north-junction"),
        (1, "s142", "S142 doorway opposite the elevators", 699, 874, "lift-lobby"),
        (1, "s140", "S140 hallway approach via S140C", 690, 881, "south-junction"),
        (1, "s120", "S120 hallway approach via S120D", 786, 855, "south-hall"),
        (2, "n255", "N255 doorway", 549, 454, "north"),
        (2, "n211", "N211 south doorway", 606, 854, "south-junction"),
        (2, "s240", "S240 hallway approach", 690, 866, "south-junction"),
        (2, "s220", "S220 north hallway approach", 863, 842, "south-hall"),
    ]
    for floor, key, label, x, y, junction in rooms:
        ident = node(f"ilc-door-{key}-f{floor}", floor, label, x, y)
        link(f"ilc-{junction}-f{floor}", ident)

    node("ilc-entrance-south", 2, "Southwest entrance - floor 2", 508, 943)
    node("ilc-sw-lobby-f2", 2, "Southwest lobby beside N201", 563, 930)
    node("ilc-sw-junction-f2", 2, "Lobby junction near S240", 610, 908)
    link("ilc-entrance-south", "ilc-sw-lobby-f2")
    link("ilc-sw-lobby-f2", "ilc-sw-junction-f2")
    link("ilc-sw-junction-f2", "ilc-south-junction-f2")
    node("ilc-entrance-north-f1", 1, "North entrance beside N155 - floor 1", 476, 400)
    link("ilc-entrance-north-f1", "ilc-north-f1")
    add_routes(nodes, connections)
    update_display_trace()
    data = dict(
        building_id="ilc",
        floor_sources=floors,
        source_url=floors["1"]["source_url"],
        source_sha256=hashlib.sha256(
            "".join(f["source_sha256"] for f in floors.values()).encode()
        ).hexdigest(),
        drawing_review=("UMass plan tiles traced on 2026-11-15; expanded with Ash_ver's "
                        "source-aligned corridor and room traces. Four elevators confirmed "
                        "by the user, including the North Pleasant Street shaft. Southwest "
                        "doorway on floor 2. Selected approaches only; no floors 3/4."),
        coordinate_system="image_pixels",
        resident_access_required=False,
        source_warnings=[
            "Published-plan directions; current access, doors, widths and grades are unverified.",
            "Floors 1-2 only. Confirm the listed hallway destination and floor signs.",
            "Location is manual; the selected-step marker is not a GPS position.",
        ],
        nodes=nodes,
        connections=connections,
    )
    checked = PlanWayfindingMap.model_validate(data)
    (output / "ilc.json").write_text(checked.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return checked


if __name__ == "__main__":
    result = build()
    print(f"ILC: {len(result.nodes)} landmarks, {len(result.connections)} connections")
