"""Fetch public accessibility reports for review; never publish them as routing closures."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from campus_notices.gemini import GeminiParser
from campus_notices.public_sources import PublicPost
from campus_notices.reports import refresh_reports, reports_status

ROOT = Path(__file__).resolve().parents[1]


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=ROOT / "data/public_sources.json")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()
    if args.interval < 600:
        parser.error("Use an interval of at least 600 seconds")
    output = ROOT / "data/private/external_reports.json"
    if args.demo:
        sources = [
            {
                "id": "synthetic-reports",
                "name": "Synthetic public report",
                "kind": "rss",
                "authority": "community",
            }
        ]
        output = ROOT / "data/private/demo_external_reports.json"
    else:
        sources = json.loads(args.sources.read_text(encoding="utf-8"))["sources"]
    while True:
        extractor = None
        try:
            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if key and not args.rules_only and not args.demo:
                extractor = GeminiParser(
                    key,
                    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                    cache_path=ROOT / ".cache/public_report_extractions.json",
                    max_calls=10,
                )
            options = {}
            if args.demo:
                options["fetcher"] = lambda spec, **kwargs: [
                    PublicPost(
                        native_id="demo-1",
                        url="https://example.org/synthetic-report",
                        title="Demo Center east elevator is broken",
                        text="The east elevator is broken.",
                        published_at=datetime.now(UTC),
                    )
                ]
            refresh_reports(
                sources=sources,
                output=output,
                registry_path=ROOT / "data/location_registry.json",
                extractor=extractor,
                demo=args.demo,
                **options,
            )
            status = reports_status(output)
            print(f"Reports: {status['report_count']}; status: {status['status']}", flush=True)
            for name, source in status["sources"].items():
                print(f"{name}: {source['state']} {source['message']}", flush=True)
            print(f"Saved review queue: {output}", flush=True)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            print(
                f"Refresh failed ({type(exc).__name__}); prior saved reports are unchanged.",
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
