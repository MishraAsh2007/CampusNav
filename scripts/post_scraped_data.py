"""Preview or upload the latest processed scraper results to the CampusNav Data API."""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import AwareDatetime, TypeAdapter

from backend.main import Building, BuildingWrite
from backend.scraper_imports import OfficialSourceSnapshot, PublicSourceSnapshot
from campus_notices.cache import read_snapshot
from campus_notices.reports import read_reports

ROOT = Path(__file__).resolve().parents[1]
TIMESTAMP = TypeAdapter(AwareDatetime)
DOOR_OPENERS = {"push-button": True, "automatic": True, "manual": False}


def building_uploads(path):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    uploads = []
    for row in catalog["buildings"]:
        elevators = row["elevators"]
        uploads.append(
            BuildingWrite.model_validate(
                {
                    "id": row["id"],
                    "name": row["name"],
                    **row["location"],
                    "entrances": [
                        {
                            "name": entrance["name"],
                            "id": entrance["id"],
                            "lat": entrance["lat"],
                            "lng": entrance["lng"],
                            "step_free": entrance.get("step_free"),
                            "hasAutoDoorOpener": DOOR_OPENERS.get(entrance.get("door_type")),
                            "IsKeyCardRequired": entrance.get("keycard_required"),
                        }
                        for entrance in row["entrances"]
                    ],
                    "elevator_count": elevators.get("total_count"),
                    "elevators": [
                        {
                            "location": point["name"], "lat": point["lat"], "lng": point["lng"],
                            "asset_id": point["id"], "building_id": row["id"],
                        }
                        for point in elevators["list"]
                    ],
                }
            )
        )
    if len({building.id for building in uploads}) != len(uploads):
        raise ValueError("Building IDs must be unique")
    return uploads


def official_uploads(path):
    snapshot = read_snapshot(path)
    if snapshot.synthetic:
        print("Skipping official demo snapshot.")
        return []

    status_path = path.with_name(f"{path.stem}.status.json")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if (
        status.get("status") not in {"success", "fallback"}
        or TIMESTAMP.validate_python(status.get("attempted_at")) != snapshot.generated_at
    ):
        print("Skipping official snapshot. The latest refresh did not publish it successfully.")
        return []

    return [
        OfficialSourceSnapshot(
            source_id=source_id,
            observed_at=state.observed_at,
            records=[row for row in snapshot.closures if row.source_id == source_id],
        )
        for source_id, state in snapshot.source_status.items()
        if state.mode == "live"
    ]


def public_uploads(path):
    snapshot = read_reports(path)
    if snapshot.synthetic:
        print("Skipping public demo snapshot.")
        return []

    return [
        PublicSourceSnapshot(
            source_id=source_id,
            observed_at=state.last_success_at,
            records=[row for row in snapshot.reports if row.source_id == source_id],
        )
        for source_id, state in snapshot.sources.items()
        if state.state == "live" and state.last_success_at == state.attempted_at
    ]


def load_uploads(path, load):
    try:
        uploads = load(path)
    except FileNotFoundError:
        print(f"Skipping {path.name}. Snapshot or refresh status file is missing.")
        return []
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not read {path.name} ({type(exc).__name__}).") from None
    if not uploads:
        print(f"{path.name} has no successful live sources to upload.")
    return uploads


def parse_api_url(value):
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ValueError("Invalid Data API base URL.") from None
    local_http = url.scheme == "http" and url.host in {"localhost", "127.0.0.1", "::1"}
    if (
        not url.host
        or (url.scheme != "https" and not local_http)
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise ValueError("Use a Data API base URL with HTTPS or a local HTTP address.")
    return url


def post_uploads(uploads, api_url, key):
    failed = False
    with httpx.Client(base_url=api_url, timeout=20, follow_redirects=False) as client:
        for upload in uploads:
            building = isinstance(upload, Building)
            endpoint = "buildings" if building else "scraper-imports"
            name = f"building:{upload.id}" if building else upload.storage_id
            collection = "Buildings" if building else upload.collection_name
            try:
                response = client.post(
                    endpoint,
                    json=upload.model_dump(mode="json"),
                    headers={"X-Admin-Key": key},
                )
                if (
                    building
                    and response.status_code == 409
                    and response.json().get("detail") == "Building ID already exists"
                ):
                    print(f"{name} already exists in {collection}.")
                    continue
                response.raise_for_status()
                result = response.json()
                if building and result.get("id") != upload.id:
                    raise ValueError("Unexpected building ID")
                applied = True if building else result.get("applied")
                if type(applied) is not bool:
                    raise ValueError("Unexpected import response")
                if not building and result.get("collection") != collection:
                    raise ValueError("Unexpected import destination")
            except httpx.HTTPStatusError as exc:
                print(f"{name} failed (HTTP {exc.response.status_code}).", file=sys.stderr)
                if not building and exc.response.status_code == 404:
                    print("Restart the Data API to load the new importer.", file=sys.stderr)
                if exc.response.status_code == 409:
                    print("The stored schema rejected this upload. Local input retained.", file=sys.stderr)
                failed = True
            except (httpx.RequestError, AttributeError, ValueError) as exc:
                print(f"{name} failed ({type(exc).__name__}).", file=sys.stderr)
                failed = True
            else:
                if applied:
                    print(f"{name} saved in {collection}.")
                else:
                    print(f"{collection} already has this capture or a newer one for {name}.")
    return int(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buildings", type=Path, default=ROOT / "data/buildings.json")
    parser.add_argument("--official", type=Path, default=ROOT / "data/official_snapshot.json")
    parser.add_argument("--public", type=Path, default=ROOT / "data/private/external_reports.json")
    parser.add_argument("--only", choices=("buildings", "official", "public"))
    parser.add_argument(
        "--api-url", help="Base URL of the Data API (default http://127.0.0.1:8000/api/data)"
    )
    parser.add_argument("--apply", action="store_true", help="Write to the Data API")
    args = parser.parse_args(argv)

    try:
        uploads = []
        if args.only in (None, "buildings"):
            uploads.extend(load_uploads(args.buildings, building_uploads))
        if args.only in (None, "official"):
            uploads.extend(load_uploads(args.official, official_uploads))
        if args.only in (None, "public"):
            uploads.extend(load_uploads(args.public, public_uploads))
        if not uploads:
            print("No uploads prepared.", file=sys.stderr)
            return 1
        for upload in uploads:
            if isinstance(upload, Building):
                print(f"building:{upload.id} -> Buildings", flush=True)
            else:
                print(
                    f"{upload.storage_id} -> {upload.collection_name}: "
                    f"{len(upload.records)} records",
                    flush=True,
                )
        if not args.apply:
            print("Preview complete. Use --apply to upload.")
            return 0

        config = dotenv_values(ROOT / "backend/.env")
        base = (
            args.api_url
            or os.getenv("CAMPUSNAV_API_URL")
            or config.get("CAMPUSNAV_API_URL")
            or "http://127.0.0.1:8000/api/data"
        )
        key = os.getenv("CAMPUSNAV_ADMIN_KEY") or config.get("CAMPUSNAV_ADMIN_KEY")
        if not key:
            raise ValueError("Set CAMPUSNAV_ADMIN_KEY in your environment or backend/.env.")
        api_url = parse_api_url(base)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return post_uploads(uploads, api_url, key)


if __name__ == "__main__":
    raise SystemExit(main())
