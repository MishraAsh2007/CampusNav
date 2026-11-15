"""Build scoped, drawing-only Old Chapel, North D and Goodell wayfinding.

Coordinates are authored from the pinned source editions, never room-label
projections. They describe floor-local landmarks, not measured accessible paths.
"""

import argparse
import hashlib
import json
from itertools import pairwise
from pathlib import Path

import pymupdf

from campus_notices.cache import atomic_json
from campus_notices.plan_integrity import require_reviewed_source
from campus_routing.plan_wayfinding import PlanWayfindingMap
from scripts.build_brown_trace import _source_url

ROOT = Path(__file__).resolve().parents[1]
CHAPEL_URL = (
    "https://umass.sharepoint.com/:b:/s/AFWD/"
    "EUvuER7_lA1Gl8wwCMWMLcgB8nbMyQSdkpLS1kstwgZVOg?e=UBC36N"
)
GOODELL_URL = (
    "https://www.umass.edu/sites/default/files/2025-04/Goodell%20Floorplan%20March%202025.jpg"
)
NORTH_PLANS = {"1": "673-01.pdf", **dict.fromkeys("2345", "673-02.03.04.05.pdf")}
CHAPEL_CROPS = {"1": (190, 65, 505, 320), "2": (180, 480, 365, 675)}
GOODELL_CROPS = {
    "3": (0, 2070, 2500, 4013),
    "4": (0, 0, 2450, 2000),
    "5": (2800, 2070, 5326, 4013),
    "6": (2800, 0, 5326, 2000),
}


class Trace:
    def __init__(self, building, sources, *, resident=False, pixels=True, warnings=()):
        self.building, self.sources = building, sources
        self.resident, self.pixels = resident, pixels
        self.warnings, self.nodes, self.edges = list(warnings), {}, []

    def node(self, floor, name, x, y, label):
        key = f"{name}-{floor}"
        value = dict(id=key, label=label, x=x, y=y, floor_id=floor)
        if key in self.nodes and self.nodes[key] != value:
            raise ValueError("Conflicting authored landmark")
        self.nodes[key] = value
        return key

    def link(self, a, b, *, kind="corridor", asset=None, evidence=None, stops=None):
        self.edges.append(
            dict(
                id=f"{a}--{b}",
                start=a,
                end=b,
                kind=kind,
                asset_id=asset or f"{self.building}-{a}--{b}",
                evidence=evidence
                or "Shared circulation visually traced on the cited floor drawing.",
                **(dict(served_floor_evidence=stops) if stops else {}),
            )
        )

    def chain(self, floor, points):
        ids = [self.node(floor, *p) for p in points]
        for a, b in pairwise(ids):
            self.link(a, b)
        return ids

    def branch(self, floor, start, name, x, y, label, *, door=False):
        key = self.node(floor, name, x, y, label)
        self.link(f"{start}-{floor}", key, kind="door" if door else "corridor")
        return key

    def elevator(self, floors, asset, evidence):
        for a, b in pairwise(floors):
            self.link(
                f"elevator-{a}",
                f"elevator-{b}",
                kind="elevator",
                asset=asset,
                evidence="Same mapped elevator core has a landing on both source floors.",
                stops=evidence,
            )

    def result(self):
        first = next(iter(self.sources.values()))
        return PlanWayfindingMap(
            building_id=self.building,
            source_url=first["url"],
            source_sha256=first["sha256"],
            floor_sources=self.sources,
            nodes=list(self.nodes.values()),
            connections=self.edges,
            coordinate_system="image_pixels" if self.pixels else "pdf_points",
            resident_access_required=self.resident,
            source_warnings=self.warnings,
            drawing_review="Manually traced shared circulation and selected destination approaches "
            "on the pinned official drawings. No physical access survey or measured grades.",
        )


def old_chapel(sources):
    t = Trace(
        "old-chapel",
        sources,
        warnings=[
            "2017 renovation guide: two main visitor floors only; basement and tower excluded.",
            "Stage route stops at the ramp approach; ramp slope and stage access are not verified.",
            "Conference-room availability depends on event access. Restroom routes are not traced.",
            "old-chapel-elevator-bank is a drawing bank ID, not an official individual-car ID.",
        ],
    )
    t.chain(
        "1",
        [
            ("entry-threshold", 983, 500, "Main pavilion entry threshold"),
            ("pavilion", 930, 500, "Main entry pavilion"),
            ("inner-entry", 870, 530, "Inner pavilion opening"),
            ("lobby", 758, 500, "First-floor lobby"),
            ("common-east", 600, 500, "East side of common area"),
            ("common-area", 460, 500, "Common area"),
            ("common-north", 460, 310, "Common area north aisle"),
            ("display-bypass", 235, 310, "North of display case"),
            ("conference-approach", 235, 390, "Conference-room doorway approach"),
        ],
    )
    t.branch("1", "lobby", "elevator", 780, 457, "First-floor elevator landing")
    t.branch(
        "1",
        "conference-approach",
        "conference-room",
        195,
        395,
        "Conference-room entrance",
        door=True,
    )
    t.chain(
        "2",
        [
            ("elevator", 560, 360, "Second-floor elevator landing"),
            ("east-hall", 558, 430, "East hall beside open-to-below void"),
            ("auditorium-door", 525, 430, "Auditorium east opening"),
            ("auditorium", 485, 430, "Auditorium east aisle"),
            ("auditorium-north", 460, 235, "Auditorium north aisle"),
            ("stage-ramp-approach", 235, 265, "Stage ramp approach; stop before the ramp"),
        ],
    )
    t.elevator(
        ["1", "2"],
        "old-chapel-elevator-bank",
        "The guide shows landings on both main floors and describes the accessibility "
        "elevator installed in the 2017 renovation. No basement or tower stop inferred.",
    )
    return t.result()


def north_d(sources):
    t = Trace(
        "north-d",
        sources,
        resident=True,
        pixels=False,
        warnings=[
            "Resident/keycard permission required; confirmation is not an access credential.",
            "Upper-floor endpoints are shared-hall approaches outside apartments, not bedrooms.",
            "Unit 01 is not inferred from the ambiguous D201E bedroom label; 02 is excluded.",
            "Unlabeled first-floor east-wing rooms and private offices are excluded.",
            "Two adjacent shafts are drawn; umass-elevator-148 represents the bank, not car count.",
            "Outdoor joins require the separate source-matched portal registry; "
            "the floor drawing alone has no geographic coordinates.",
        ],
    )
    t.chain(
        "1",
        [
            ("exit-threshold", 467, 632, "Southwest entrance, drawing-bottom lobby threshold"),
            ("vestibule", 467, 605, "South entry vestibule"),
            ("lobby", 467, 550, "Shared first-floor lobby"),
            ("bank-hall", 400, 550, "Hall in front of elevator bank"),
            ("elevator", 400, 539, "First-floor elevator-bank landing"),
        ],
    )
    t.chain(
        "1",
        [
            ("bank-hall", 400, 550, "Hall in front of elevator bank"),
            ("hall-south", 348, 550, "South shared hall"),
            ("bath-approach", 348, 470, "Hall outside shared bathrooms D122/D123"),
            ("laundry-approach", 348, 430, "Hall outside laundry D124"),
            ("hall-125", 348, 375, "Hall near D125"),
            ("hall-126", 348, 315, "Hall near D126/D127"),
            ("hall-128", 348, 175, "Hall near D128/D129"),
            ("hall-north", 348, 100, "North shared hall near D131"),
        ],
    )
    t.branch("1", "lobby", "east-lobby", 535, 550, "East side of shared lobby")
    # Stop in shared lobby, outside each lounge; no assumed access through staff rooms.
    t.branch("1", "east-lobby", "lounge-114", 540, 535, "Outside lounge D114")
    t.branch("1", "east-lobby", "lounge-115", 540, 563, "Outside lounge D115")
    for floor in "2345":
        t.chain(
            floor,
            [
                ("north-hall", 299, 105, "North shared hall"),
                ("hall-06-07", 299, 145, "Shared hall by apartments 06/07"),
                ("hall-04-05", 299, 255, "Shared hall by apartments 04/05"),
                ("hall-03", 299, 397, "Shared hall by apartment 03"),
                ("hall-corner", 299, 430, "Shared hall corner"),
                ("elevator", 326, 430, f"Floor {floor} elevator-bank landing"),
                ("hall-08-09", 452, 430, "Shared hall by apartments 08/09"),
                ("hall-10-11", 560, 430, "Shared hall by apartments 10/11"),
                ("hall-12-13", 670, 430, "Shared hall by apartments 12/13"),
                ("east-hall", 697, 430, "East shared hall; stairs excluded"),
            ],
        )
        for group, units in [
            ("06-07", [6, 7]),
            ("04-05", [4, 5]),
            ("03", [3]),
            ("08-09", [8, 9]),
            ("10-11", [10, 11]),
            ("12-13", [12, 13]),
        ]:
            anchor = t.nodes[f"hall-{group}-{floor}"]
            for unit in units:
                # A hall landmark, not an exact doorway coordinate or private interior.
                t.branch(
                    floor,
                    f"hall-{group}",
                    f"apartment-{floor}{unit:02}",
                    anchor["x"],
                    anchor["y"],
                    f"Shared hall outside apartment D{floor}{unit:02}; locate signed door",
                )
    t.elevator(
        list("12345"),
        "umass-elevator-148",
        "First-floor plan shows the same bank as the upper-floor template. "
        "The drawing header explicitly covers floors 2, 3, 4 and 5; the official "
        "North Apartments page describes five-story buildings with elevators.",
    )
    return t.result()


def goodell(sources):
    t = Trace(
        "goodell",
        sources,
        warnings=[
            "March 2025 directory plan: selected student-service approaches on levels 3–6 only.",
            "Department destinations only; individual office numbers and access are not inferred.",
            "White X regions/shafts and stairs are excluded; only the red elevator core is linked.",
            "North bridges/partitions are not assumed step-free; east/west routes use south halls.",
            "umass-elevator-120 is the mapped core asset, not a verified count of cars.",
            "West level-3 and east level-5 entry landmarks have no surveyed outdoor portal join.",
        ],
    )
    t.chain(
        "3",
        [
            ("west-entry", 60, 322, "West level-3 entry threshold"),
            ("west-hall", 168, 322, "West public hall"),
            ("aisp-approach", 245, 322, "Hall outside AISP CC / MPR"),
            ("meeting-approach", 330, 322, "Hall leading to shared meeting area"),
            ("east-hall", 453, 322, "East public hall"),
            ("east-core", 453, 533, "Hall beside elevator core"),
            ("elevator", 457, 523, "Level-3 elevator landing"),
        ],
    )
    t.chain(
        "3",
        [
            ("west-hall", 168, 322, "West public hall"),
            ("mm-approach", 168, 244, "Outside MM entrance"),
            ("spi-approach", 170, 215, "Outside SPI entrance"),
        ],
    )
    t.branch("3", "meeting-approach", "shared-meeting", 330, 231, "Shared meeting room entrance")
    t.branch("3", "aisp-approach", "aisp-mpr", 245, 345, "AISP CC / MPR entrance")
    t.chain(
        "3",
        [
            ("east-core", 453, 533, "Hall beside elevator core"),
            ("center-entry", 453, 560, "Approach to cultural-center shared circulation"),
            ("center-door", 438, 560, "Cultural-center circulation doorway"),
            ("center-junction", 300, 560, "Cultural-center shared corridor"),
            ("center-west", 210, 560, "West cultural-center corridor"),
            ("mxcc", 210, 520, "Hall outside MXCC"),
            ("up", 210, 365, "Hall outside UP"),
        ],
    )
    t.branch("3", "center-west", "lacc", 210, 620, "Hall outside LACC")
    t.branch("3", "center-junction", "ykcc", 240, 579, "YKCC approach")
    t.branch("3", "center-junction", "jwecc", 315, 579, "JWECC approach")
    t.chain(
        "4",
        [
            ("elevator", 460, 558, "Level-4 elevator landing west of shaft"),
            ("core-south", 460, 620, "Hall south of elevator/stair core"),
            ("south-junction", 540, 620, "South public hall junction"),
            ("east-south", 900, 620, "Southeast public hall"),
            ("career-services", 900, 400, "Hall outside Career Services"),
            ("east-north", 900, 260, "Northeast public hall"),
            ("stonewall-approach", 760, 260, "Hall outside Stonewall Center"),
            ("stonewall", 760, 235, "Stonewall Center entrance approach"),
        ],
    )
    t.branch(
        "4",
        "core-south",
        "disability-services",
        447,
        594,
        "Disability Services suite 435 entrance approach",
    )
    t.chain(
        "4",
        [
            ("south-junction", 540, 620, "South public hall junction"),
            ("west-core", 540, 350, "West side of restroom core"),
            ("north-junction", 540, 280, "North public hall"),
            ("cmass", 390, 280, "CMASS entrance approach"),
        ],
    )
    t.branch("4", "west-core", "shared-staff", 558, 350, "Shared staff room approach")
    t.branch("4", "north-junction", "dde", 540, 205, "Hall outside DDE")
    t.branch("4", "east-south", "veterans-hall", 730, 620, "Hall outside Veterans Services")
    t.branch("4", "veterans-hall", "veterans", 730, 650, "Veterans Services entrance approach")
    t.branch("4", "east-south", "shared-meeting", 900, 650, "Shared meeting room approach")
    t.branch("4", "east-north", "cmass-east", 915, 260, "East CMASS entrance approach")
    t.chain(
        "5",
        [
            ("elevator", 428, 522, "Level-5 elevator landing west of shaft"),
            ("core-south", 428, 570, "Hall south of elevator/stair core"),
            ("south-junction", 500, 580, "South public hall"),
            ("career-services", 760, 580, "Hall outside Career Services"),
            ("east-south", 850, 580, "Southeast hall"),
            ("east-entry-hall", 850, 415, "East public hall by column entrance"),
            ("shared-lounge", 850, 360, "Hall outside shared lounge"),
            ("east-north", 850, 235, "Northeast public hall"),
            ("bernie-approach", 700, 235, "Hall outside Bernie Dallas Room"),
            ("bernie-dallas", 700, 207, "Bernie Dallas Room entrance approach"),
        ],
    )
    t.chain(
        "5",
        [
            ("south-junction", 500, 580, "South public hall"),
            ("graduate-students", 500, 450, "Dean of Graduate Students entrance approach"),
            ("shared-staff", 500, 360, "Shared staff room entrance approach"),
            ("shared-meeting-north", 500, 295, "North shared meeting room approach"),
            ("north-hall", 500, 260, "Northwest public hall"),
        ],
    )
    t.branch("5", "east-entry-hall", "east-entry", 970, 415, "East level-5 column entry threshold")
    t.branch(
        "5",
        "south-junction",
        "shared-meeting-south",
        560,
        615,
        "South shared meeting room entrance approach",
    )
    t.chain(
        "6",
        [
            ("elevator", 426, 543, "Level-6 elevator landing west of shaft"),
            ("south-west", 426, 600, "Hall south of elevator/stair core"),
            ("south-junction", 500, 600, "South public hall"),
            ("south-east", 640, 600, "Hall south of restroom core"),
            ("east-south", 850, 610, "Southeast public hall"),
            ("student-success-east", 850, 420, "East Student Success entrance approach"),
            ("east-north", 850, 265, "Northeast hall"),
        ],
    )
    t.chain(
        "6",
        [
            ("south-west", 426, 600, "Hall south of elevator/stair core"),
            ("west-south", 310, 600, "Southwest hall"),
            ("student-success-west", 310, 450, "West Student Success entrance approach"),
            ("west-north", 310, 310, "West hall beside enclosed void"),
            ("north-west", 310, 270, "Northwest public hall"),
        ],
    )
    t.branch("6", "north-west", "cesl", 310, 245, "CESL entrance approach")
    t.branch(
        "6",
        "north-west",
        "student-success-north",
        540,
        270,
        "North Student Success entrance approach",
    )
    t.branch("6", "south-east", "shared-meeting", 690, 610, "Shared meeting room entrance approach")
    t.branch("6", "south-junction", "shared-staff", 520, 590, "Shared staff room entrance approach")
    t.branch(
        "6",
        "south-junction",
        "student-success-south",
        540,
        615,
        "South Student Success entrance approach",
    )
    t.elevator(
        list("3456"),
        "umass-elevator-120",
        "The March 2025 plan explicitly draws the same red elevator shaft on service "
        "levels 3, 4, 5 and 6. Disability Services directions corroborate use between "
        "west level 3, service level 4 and east level 5. Current service is not verified.",
    )
    return t.result()


BUILDERS = {"old-chapel": old_chapel, "north-d": north_d, "goodell": goodell}


def checked(path, name):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require_reviewed_source(name, digest)
    return digest


def prepare_sources(root, building):
    folder = root / "data/private/plan_wayfinding/sources"
    folder.mkdir(parents=True, exist_ok=True)
    documents = root / "data/private/building_documents"
    sources = {}
    if building == "north-d":
        rows = json.loads((root / "data/private/residence_floorplans/manifest.json").read_text())
        by_name = {r["name"]: r for r in rows["records"]}
        for floor, name in NORTH_PLANS.items():
            row = by_name[name]
            path = Path(row["local_path"])
            digest = checked(path, name)
            with pymupdf.open(path) as doc:
                page = doc[0]
                target = folder / f"north-d-{floor}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(target)
                sources[floor] = dict(
                    url=_source_url(row["server_relative_url"]),
                    sha256=digest,
                    page="1",
                    local_image=str(target),
                    width=str(page.rect.width),
                    height=str(page.rect.height),
                )
    elif building == "old-chapel":
        path = documents / "old-chapel.pdf"
        digest = checked(path, "old-chapel-tour-guide.pdf")
        with pymupdf.open(path) as doc:
            for floor, rect in CHAPEL_CROPS.items():
                target = folder / f"old-chapel-{floor}.png"
                pix = doc[1].get_pixmap(clip=pymupdf.Rect(rect), matrix=pymupdf.Matrix(4, 4))
                pix.save(target)
                sources[floor] = dict(
                    url=CHAPEL_URL,
                    sha256=digest,
                    page="2",
                    crop_pdf_points=str(rect),
                    local_image=str(target),
                    width=str(pix.width),
                    height=str(pix.height),
                )
    else:
        path = documents / "goodell.jpg"
        digest = checked(path, "goodell-march-2025.jpg")
        # A pixel-sized PDF canvas avoids implicit JPEG DPI/point conversions.
        with pymupdf.open() as doc:
            page = doc.new_page(width=5326, height=4013)
            page.insert_image(page.rect, filename=str(path))
            for floor, rect in GOODELL_CROPS.items():
                target = folder / f"goodell-{floor}.png"
                scale = 1100 / (rect[2] - rect[0])
                pix = page.get_pixmap(clip=pymupdf.Rect(rect), matrix=pymupdf.Matrix(scale, scale))
                pix.save(target)
                sources[floor] = dict(
                    url=GOODELL_URL,
                    sha256=digest,
                    crop_image_pixels=str(rect),
                    local_image=str(target),
                    width=str(pix.width),
                    height=str(pix.height),
                )
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--building", choices=BUILDERS, action="append")
    args = parser.parse_args()
    maps = []
    for building in args.building or BUILDERS:
        sources = prepare_sources(ROOT, building)
        maps.append(BUILDERS[building](sources))
    # No existing map is overwritten if any requested source edition needs review.
    for data in maps:
        atomic_json(
            ROOT / "data/private/plan_wayfinding" / f"{data.building_id}.json",
            data.model_dump(mode="json"),
        )
        print(data.building_id, len(data.nodes), "landmarks; floors", ", ".join(data.floor_sources))


if __name__ == "__main__":
    main()
