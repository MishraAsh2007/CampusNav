"""Collect all CampusNav source families with one command and explicit cache status."""

import argparse
import time
from pathlib import Path

from campus_notices.all_sources import run_all, stages

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-only", action="store_true", help="Disable Gemini fallback")
    parser.add_argument(
        "--offline", action="store_true", help="Combine existing data without network"
    )
    parser.add_argument("--stage", action="append", choices=[s.id for s in stages()])
    parser.add_argument(
        "--rebuild-graphs",
        action="store_true",
        help="Also rebuild outdoor graphs/elevation; slower than source collection",
    )
    parser.add_argument("--watch", action="store_true", help="Repeat until Ctrl+C")
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()
    if args.interval < 300 or (args.offline and args.rebuild_graphs):
        parser.error("Use interval >= 300 seconds; graph rebuilds require live collection")
    try:
        while True:
            report = run_all(
                ROOT,
                rules_only=args.rules_only,
                offline=args.offline,
                selected=args.stage,
                rebuild_graphs=args.rebuild_graphs,
            )
            print("\nCollection:", report["status"], flush=True)
            print("Combined data: data/collected_data.json", flush=True)
            print("Source status: data/scrape_status.json", flush=True)
            print(
                "Private data/logs: data/private/collected_data.json and scrape_logs/", flush=True
            )
            print(
                "Reviewed source editions rebuild scoped drawing pilots; changed editions retain "
                "previous maps. Collection does not start the server.",
                flush=True,
            )
            if not args.watch:
                if report["status"] == "unavailable":
                    raise SystemExit(1)
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nCollector stopped; saved data retained.")


if __name__ == "__main__":
    main()
