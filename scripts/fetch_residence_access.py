"""Cache public accessibility layers for the all-residence coverage audit."""

from datetime import UTC, datetime
from pathlib import Path

import httpx

from campus_notices.cache import atomic_json
from scripts.sync_campus_access import SOURCES, fetch_layer

ROOT = Path(__file__).resolve().parents[1]


def main():
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        data = {key: fetch_layer(client, *spec) for key, spec in SOURCES.items()}
    data["observed_at"] = datetime.now(UTC).isoformat()
    atomic_json(ROOT / ".cache/residence-access.json", data)
    print("Public features:", {key: len(data[key]) for key in SOURCES})
    for row in data["buildings"]:
        attrs = row["attributes"]
        print(attrs["BuildingID"], attrs["BuildingName"])


if __name__ == "__main__":
    main()
