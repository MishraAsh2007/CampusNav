"""Fetch an OSM map extract to supplement sourced residence entrances."""

from pathlib import Path

import httpx

from scripts.build_residence_catalog import BBOX


def main():
    response = httpx.get(
        "https://api.openstreetmap.org/api/0.6/map",
        params={"bbox": ",".join(map(str, BBOX))},
        timeout=90,
    )
    response.raise_for_status()
    if not response.content.startswith(b"<?xml"):
        raise ValueError("Expected OSM XML")
    path = Path(".cache/residence-map.osm")
    path.write_bytes(response.content)
    print("Saved public OSM extract bytes:", len(response.content))


if __name__ == "__main__":
    main()
