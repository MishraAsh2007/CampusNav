"""Scrape public library elevator regions and historical car-service references."""

import argparse
from pathlib import Path

from campus_notices.library_elevators import collect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/library_elevator_sources.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/library-elevator-research")
    args = parser.parse_args()
    result = collect(args.output, args.cache)
    print(
        len(result["floors"]),
        "floor pages;",
        sum(len(f["regions"]) for f in result["floors"]),
        "elevator regions across those pages;",
    )
    print(len(result["historical_cars"]), "historical car references. No routing graph changed.")
    print("Saved:", args.output)


if __name__ == "__main__":
    main()
