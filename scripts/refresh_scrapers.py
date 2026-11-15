"""Refresh official UMass notices and public reports in one run."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def refresh_cycle(shared, *, storage_state=None, public_sources=None):
    official_args = ["--storage-state", str(storage_state)] if storage_state else []
    public_args = ["--sources", str(public_sources)] if public_sources else []
    failed = []
    for title, module, options in (
        ("Official notices", "scripts.refresh_notices", official_args),
        ("Public reports", "scripts.refresh_reports", public_args),
    ):
        print(f"\n{title}", flush=True)
        result = subprocess.run(
            [sys.executable, "-u", "-m", module, *shared, *options], cwd=ROOT, check=False
        )
        if result.returncode:
            failed.append(title)
    if failed:
        print(f"Worker failed: {', '.join(failed)}", file=sys.stderr, flush=True)
    return int(bool(failed))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-only", action="store_true", help="Never call Gemini")
    parser.add_argument("--demo", action="store_true", help="Run both workers offline on fixtures")
    parser.add_argument(
        "--storage-state", type=Path, help="Use a different SharePoint session file"
    )
    parser.add_argument("--public-sources", type=Path, help="Use a different public source config")
    parser.add_argument("--watch", action="store_true", help="Repeat until Ctrl+C")
    parser.add_argument("--interval", type=int, default=3600, help="Seconds between watch cycles")
    args = parser.parse_args(argv)
    if args.interval < 600:
        parser.error("Use an interval of at least 600 seconds")
    if args.demo and (args.storage_state or args.public_sources):
        parser.error("Demo runs only use synthetic sources")
    shared = [
        flag
        for flag, enabled in (("--rules-only", args.rules_only), ("--demo", args.demo))
        if enabled
    ]
    try:
        while True:
            status = refresh_cycle(
                shared,
                storage_state=args.storage_state.resolve() if args.storage_state else None,
                public_sources=args.public_sources.resolve() if args.public_sources else None,
            )
            if not args.watch:
                return status
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
