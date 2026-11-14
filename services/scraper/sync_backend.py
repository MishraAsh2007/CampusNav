"""Send current and upcoming SIN elevator notices to the backend's official list, merging.

    python sync_backend.py --dry-run     # show what would be sent, change nothing
    python sync_backend.py               # merge into POST /official-reports

The backend's POST /official-reports replaces the whole official list, and other scrapers
(e.g. role-3-web-scraper's facilities scraper) write to it too. So this script:

  1. GETs the current official list,
  2. keeps every entry it does not own (ids not starting with "sin-"),
  3. replaces its own entries with the notices in the latest CSV export,
  4. POSTs the merged list.

If step 1 fails, nothing is posted. Another writer that posts between steps 1 and 4 loses
its update until it runs again (both run on schedules, so the gap is short).

Env (same names as role-3-web-scraper): CAMPUSNAV_API_URL (default http://127.0.0.1:8000),
CAMPUSNAV_ADMIN_KEY (must match the backend's key).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from parse_sin import (
    DEFAULT_CSV, ELEVATOR_RADIUS_M, MAX_BUILDING_RADIUS_M, TZ, BuildingIndex, Notice, _label, _slug,
    blocks_elevators, parse_csv,
)
from umass_gis import load_gis

OWN_PREFIX = "sin-"
# Fields the backend's OfficialNotice accepts (it rejects unknown fields).
NOTICE_FIELDS = ("id", "type", "radius", "lat", "lng", "title", "description", "details", "start_time", "end_time")
HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
load_dotenv(HERE.parents[1] / ".env")


def sin_entries(notices: list[Notice], index: BuildingIndex, now: datetime,
                skip_partial: bool = False, include_freight: bool = False) -> list[dict]:
    """Backend OfficialNotice dicts for every elevator-blocking notice that hasn't ended."""
    entries = []
    for n in notices:
        if not blocks_elevators(n, skip_partial, include_freight) or n.ends_at <= now:
            continue
        when = f"{n.starts_at:%b %d %I:%M %p} to {n.ends_at:%b %d %I:%M %p}".replace(" 0", " ")
        for name in n.buildings:
            b = index.by_name[name]
            common = {
                "type": "elevator",
                "title": f"{_label(n)} at {name}",
                "description": f"{_label(n)} at {name}, {when} (UMass SIN #{n.doc_id})",
                "details": n.description[:500] or None,
                "start_time": n.starts_at.isoformat(),
                "end_time": n.ends_at.isoformat(),
            }
            if b["elevators"]:
                for e in b["elevators"]:
                    entries.append({"id": f"{OWN_PREFIX}{n.doc_id}-{_slug(name)}-e{e['id']}",
                                    "lat": e["lat"], "lng": e["lon"], "radius": ELEVATOR_RADIUS_M, **common})
            else:
                lat, lon = b["centroid"]
                entries.append({"id": f"{OWN_PREFIX}{n.doc_id}-{_slug(name)}", "lat": lat, "lng": lon,
                                "radius": min(b["radius_m"] + 5, MAX_BUILDING_RADIUS_M), **common})
    return entries


def as_notice(saved: dict) -> dict:
    """Turn a GET /official-reports item back into the POST shape, unchanged otherwise."""
    d = {k: saved[k] for k in NOTICE_FIELDS if k in saved}
    if ("lat" not in d or "lng" not in d) and isinstance(saved.get("location"), dict):
        d["lat"], d["lng"] = saved["location"]["lat"], saved["location"]["lng"]
    return d


def merge(current: list[dict], ours: list[dict]) -> tuple[list[dict], int]:
    kept = [as_notice(c) for c in current if not str(c.get("id", "")).startswith(OWN_PREFIX)]
    return kept + ours, len(kept)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--api", default=os.environ.get("CAMPUSNAV_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--at", help="treat this local time as now, e.g. 2026-06-09T07:00 (testing)")
    p.add_argument("--dry-run", action="store_true", help="print the plan, don't POST")
    p.add_argument("--skip-partial", action="store_true")
    p.add_argument("--include-freight", action="store_true")
    args = p.parse_args()
    api = args.api.rstrip("/")

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 1
    now = datetime.fromisoformat(args.at).replace(tzinfo=TZ) if args.at else datetime.now(TZ)
    index = BuildingIndex(load_gis())
    ours = sin_entries(parse_csv(args.csv, index), index, now, args.skip_partial, args.include_freight)

    try:
        r = requests.get(f"{api}/official-reports", timeout=15)
        r.raise_for_status()
        current = r.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Could not read the current official list from {api}; nothing posted. ({exc})", file=sys.stderr)
        return 2

    merged, kept = merge(current, ours)
    replaced = sum(1 for c in current if str(c.get("id", "")).startswith(OWN_PREFIX))
    print(f"official list at {api}: {len(current)} now | keeping {kept} from other sources | "
          f"replacing {replaced} SIN entries with {len(ours)} | posting {len(merged)}")
    for e in ours[:5]:
        print(f"   {e['id']}: {e['description']}")

    if args.dry_run:
        print("dry run: nothing posted")
        return 0
    key = os.environ.get("CAMPUSNAV_ADMIN_KEY", "")
    if not key:
        print("CAMPUSNAV_ADMIN_KEY is not set; nothing posted.", file=sys.stderr)
        return 1
    resp = requests.post(f"{api}/official-reports", json={"closures": merged},
                         headers={"X-Admin-Key": key}, timeout=30)
    if resp.status_code != 200:
        print(f"Backend rejected the list: HTTP {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        return 3
    print(f"posted: backend now has {len(resp.json())} official entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
