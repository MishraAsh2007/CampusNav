"""Build limited central-campus wayfinding from inspected plans and official directions."""

import argparse
import hashlib
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from campus_notices.cache import atomic_json
from campus_routing.plan_wayfinding import PlanWayfindingMap

ROOT = Path(__file__).resolve().parents[1]
SU_URL = "https://www.umass.edu/student-life/student-union/art-gallery/accessibility-contact"


def student_union(html):
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    for expected in [
        "Room 235",
        "SORC",
        "lower level",
        "Craft Center",
        "elevators",
        "Black Box Theater",
        "past the SORC office",
    ]:
        if expected not in text:
            raise ValueError("Student Union direction source changed")
    digest = hashlib.sha256(html.encode()).hexdigest()
    nodes = [
        dict(id="sorc-landmark", label="SORC landmark inside Student Union", floor_id="main-level"),
        dict(id="elevator-main", label="Elevators past SORC", floor_id="main-level"),
        dict(id="elevator-lower", label="Lower-level elevator landing", floor_id="lower-level"),
        dict(
            id="gallery-235",
            label="Art Gallery 235, between Craft Center and Black Box Theater",
            floor_id="lower-level",
        ),
    ]
    edges = [
        dict(
            id="sorc-to-elevator",
            start="sorc-landmark",
            end="elevator-main",
            kind="corridor",
            asset_id="su-gallery-approach",
            evidence="Official gallery directions locate elevators past SORC and left.",
            forward_instruction="From the SORC landmark, continue past the office "
            "and look left for the elevators.",
            reverse_instruction="Return along the approach to the SORC landmark; "
            "check local signs.",
        ),
        dict(
            id="su-gallery-elevator",
            start="elevator-main",
            end="elevator-lower",
            kind="elevator",
            asset_id="umass-elevator-122",
            evidence="Official gallery accessibility instructions specify the elevator.",
            served_floor_evidence="UMass explicitly directs visitors from inside the Student Union "
            "past SORC to the elevators down to the lower level. "
            "Numeric floor labels are not inferred.",
        ),
        dict(
            id="lower-to-gallery",
            start="elevator-lower",
            end="gallery-235",
            kind="corridor",
            asset_id="su-gallery-approach",
            evidence="Official source identifies Gallery 235 between "
            "Craft Center and Black Box Theater; exact corridor geometry is not provided.",
            forward_instruction="On the lower level, find Art Gallery 235 between the Craft Center "
            "and Black Box Theater. Follow local signs; exact turns are not documented.",
            reverse_instruction="Return to the lower-level elevator landmark, "
            "following local signs.",
        ),
    ]
    source = dict(url=SU_URL, sha256=digest)
    return PlanWayfindingMap(
        building_id="student-union",
        coordinate_system="landmarks_only",
        resident_access_required=False,
        source_url=SU_URL,
        source_sha256=digest,
        floor_sources={"main-level": source, "lower-level": source},
        nodes=nodes,
        connections=edges,
        source_warnings=[
            "Official landmark directions only; no floor-plan line or exact turns available.",
            "Numeric floor labels and geographic entrance alignment are not inferred.",
        ],
        drawing_review="Official UMass gallery directions encoded as a landmark sequence. "
        "Not a measured building graph or full Student Union coverage.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    cache = ROOT / ".cache/central-plans/su-gallery.html"
    if args.offline:
        html = cache.read_text(encoding="utf-8")
    else:
        with httpx.Client(timeout=30, follow_redirects=True) as c:
            response = c.get(SU_URL)
            response.raise_for_status()
            html = response.text
    su = student_union(html)  # Validate before saving source or publishing the map.
    cache.write_text(html, encoding="utf-8")
    folder = ROOT / "data/private/plan_wayfinding"
    for data in [su]:
        atomic_json(folder / (data.building_id + ".json"), data.model_dump(mode="json"))
        print(data.building_id, len(data.nodes), "landmarks;", data.coordinate_system)


if __name__ == "__main__":
    main()
