"""Download source-backed UMass residence-hall floor plans from SharePoint."""

import argparse
from pathlib import Path

from campus_notices.residence_plans import refresh_residence_plans

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=ROOT / "data/private/sharepoint-session.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/manifest.json",
    )
    parser.add_argument(
        "--download-root",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/files",
    )
    args = parser.parse_args()
    result = refresh_residence_plans(
        storage_state=args.storage_state,
        output=args.output,
        download_root=args.download_root,
    )
    print(
        f"Downloaded {result['file_count']} plan files for "
        f"{result['building_count']} buildings to {args.download_root}"
    )


if __name__ == "__main__":
    main()
