"""Save a small inspected Brown plan trace; unresolved measurements remain null."""

import json
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_notices.trace_annotations import PlanTrace

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "data/private/residence_floorplans/workspaces/brown-house"
    evidence = json.loads((folder / "evidence.json").read_text())
    source = next(p for p in evidence["plans"] if p["name"].startswith("426-02."))
    # Coordinates inspected on the 1.5x rendered grouped-floor drawing. Limit the
    # trace to the clearly visible main corridor; do not extend it through suites.
    trace = PlanTrace(
        id="brown-upper-main-corridor-east",
        source_id=source["source_id"],
        page=1,
        floors=source["floors"],
        kind="corridor",
        points=[(425, 488), (600, 488), (840, 488), (1010, 488)],
        coordinate_system="render_pixels",
        evidence="Visible horizontal main corridor on the grouped second-through-eighth "
        "floor drawing. Endpoints stop before stair landings and the elevator-lobby area. "
        "No suite threshold or served-floor elevator connection inferred. The plan is "
        "marked Not To Scale; dimension-based calibration remains outstanding.",
    )
    path = folder / "annotations" / (trace.id + ".json")
    if path.exists():
        print("Existing annotation retained:", path)
        return
    atomic_json(path, trace.model_dump(mode="json"))
    print("Saved private candidate drawing trace:", path)
    print("No metric length, access permission or route publication claimed.")


if __name__ == "__main__":
    main()
