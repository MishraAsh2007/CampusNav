"""CLI: build the campus graph once and write data/graph.graphml.

    python scripts/build_graph.py                 # full build (OSM + elevation)
    python scripts/build_graph.py --no-elevation  # offline-ish: flat grades, for plumbing tests
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.graph.build import build_graph  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-elevation", action="store_true", help="skip elevation lookup (grades = 0)")
    p.add_argument("--out", type=Path, default=config.GRAPH_PATH)
    p.add_argument("--provider", choices=["opentopodata", "epqs", "openmeteo"], help="elevation provider")
    args = p.parse_args()

    if args.provider:
        config.ELEVATION_PROVIDER = args.provider
    build_graph(out_path=args.out, with_elevation=not args.no_elevation)


if __name__ == "__main__":
    main()
