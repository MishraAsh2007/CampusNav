"""Scrape SharePoint first, parse rules first, optionally use Gemini, and cache closures."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from campus_notices.gemini import GeminiError, GeminiParser
from campus_notices.pipeline import refresh
from campus_notices.sharepoint import LIST_ID, SITE
from campus_notices.sources import SourceError

ROOT = Path(__file__).resolve().parents[1]


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument(
        "--spreadsheet", type=Path, help="Offline-only import; bypass live scraping"
    )
    inputs.add_argument("--sources", type=Path, help="JSON source configuration")
    inputs.add_argument("--demo", action="store_true", help="Isolated synthetic offline example")
    parser.add_argument(
        "--fallback-spreadsheet",
        type=Path,
        default=Path.home() / "Downloads/Book1.xlsx",
        help="Used only if the live list and saved scrape are unavailable",
    )
    parser.add_argument(
        "--storage-state", type=Path, default=ROOT / "data/private/sharepoint-session.json"
    )
    parser.add_argument("--locations", type=Path, default=ROOT / "data/location_registry.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rules-only", action="store_true", help="Never call Gemini")
    parser.add_argument("--max-gemini-calls", type=int, default=25)
    parser.add_argument("--watch", action="store_true", help="Repeat hourly until Ctrl+C")
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()
    if args.max_gemini_calls < 0 or args.interval < 60:
        parser.error("max-gemini-calls must be nonnegative and interval at least 60 seconds")
    if args.demo:
        sources = [
            {
                "id": "synthetic-notices",
                "kind": "json",
                "path": str(ROOT / "examples/role3/notices.json"),
            }
        ]
        locations = ROOT / "examples/role3/locations.json"
        output = args.output or ROOT / "data/private/demo_official_snapshot.json"
        if output.resolve() == (ROOT / "data/official_snapshot.json").resolve():
            parser.error("Demo data cannot replace the production snapshot")
        base = ROOT
    else:
        locations = args.locations
        output = args.output or ROOT / "data/official_snapshot.json"
        if args.spreadsheet:
            sources = [
                {
                    "id": "umass-export",
                    "kind": args.spreadsheet.suffix.lstrip(".").lower(),
                    "path": str(args.spreadsheet.resolve()),
                }
            ]
            base = ROOT
        elif args.sources:
            sources = json.loads(args.sources.read_text(encoding="utf-8"))["sources"]
            base = args.sources.resolve().parent
        else:
            sources = [
                {
                    "id": "umass-maintenance",
                    "kind": "sharepoint",
                    "site_url": SITE,
                    "list_id": LIST_ID,
                    "storage_state": str(args.storage_state.resolve()),
                    "cache": str(ROOT / "data/private/sharepoint-notices.json"),
                    "fallback": {
                        "kind": args.fallback_spreadsheet.suffix.lstrip(".").lower(),
                        "path": str(args.fallback_spreadsheet.resolve()),
                    },
                }
            ]
            base = ROOT
    while True:
        extractor = None
        try:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key and not args.rules_only and not args.demo:
                extractor = GeminiParser(
                    api_key,
                    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                    cache_path=ROOT / ".cache/notice_extractions.json",
                    max_calls=args.max_gemini_calls,
                )
            print(
                "Parser: rules first; "
                + (
                    "Gemini fallback enabled"
                    if extractor
                    else "unresolved text goes to review (no Gemini calls)"
                ),
                flush=True,
            )
            # Only the synthetic example uses a fixed clock.
            now = datetime(2026, 11, 14, 12, tzinfo=UTC) if args.demo else datetime.now(UTC)
            snapshot = refresh(
                sources=sources,
                base=base,
                registry_path=locations,
                output=output,
                extractor=extractor,
                now=now,
                demo=args.demo,
            )
            print(json.dumps(snapshot.counts, indent=2), flush=True)
            for source_id, status in snapshot.source_status.items():
                print(
                    f"Source {source_id}: {status.mode}; observed {status.observed_at.isoformat()}",
                    flush=True,
                )
                if status.message:
                    print(status.message, flush=True)
            print(
                f"Snapshot: {output}\n"
                f"Review queue: {output.with_name(output.stem + '.review.json')}",
                flush=True,
            )
        except KeyboardInterrupt:
            return
        except Exception as exc:
            print(
                f"Refresh failed ({type(exc).__name__}). Previous published closures are retained.",
                flush=True,
            )
            if isinstance(exc, (SourceError, FileNotFoundError, GeminiError)):
                print(str(exc), flush=True)
            print(
                "For SharePoint sign-in run .\\login-notices.cmd. Check source paths and access. "
                "No API key is required with --rules-only.",
                flush=True,
            )
            if not args.watch:
                raise SystemExit(1) from None
        finally:
            if extractor:
                extractor.close()
        if not args.watch:
            return
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
