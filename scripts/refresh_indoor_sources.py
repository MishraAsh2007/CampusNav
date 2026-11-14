"""Scrape official floor/room directories and public floor-plan image references."""

import argparse
from pathlib import Path

from campus_notices.indoor_sources import create_indoor_drafts, refresh_indoor_sources

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/indoor_sources.json")
    parser.add_argument("--draft-dir", type=Path, default=ROOT / "data/indoor")
    args = parser.parse_args()
    payload = refresh_indoor_sources(args.output)
    for path in create_indoor_drafts(payload, args.draft_dir):
        print(f"Created non-routable floor reference: {path}")
    for name, state in payload["sources"].items():
        print(f"{name}: {state['mode']}; {state['count']} records")
    print(f"Saved {len(payload['records'])} source records; corridor topology still needs review.")
    if all(s["mode"] == "unavailable" for s in payload["sources"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
