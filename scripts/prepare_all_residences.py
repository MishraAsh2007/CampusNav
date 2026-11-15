"""Prepare source evidence and editable indoor drafts for all downloaded dorm plans."""

import argparse
from pathlib import Path

from campus_notices.residence_workspace import prepare_workspaces

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/private/residence_floorplans/manifest.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/private/residence_floorplans/workspaces"
    )
    args = parser.parse_args()
    result = prepare_workspaces(args.manifest, args.output)
    print(
        f"Prepared {result['building_count']} buildings from "
        f"{result['source_folder_count']} source folders."
    )
    print(f"Private review index: {args.output / 'index.json'}")
    print("Existing map.json and review.json edits preserved. Topology review remains required.")


if __name__ == "__main__":
    main()
