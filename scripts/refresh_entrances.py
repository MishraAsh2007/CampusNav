"""Collect additional public door-opener records and supplement campus catalogs."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from campus_notices.cache import atomic_json
from campus_notices.entrance_evidence import supplement
from campus_routing.entrance_observations import apply_door_observations, read_door_observations
from scripts.sync_campus_access import SOURCES, fetch_layer

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "OBJECTID_1,OBJECTID,GlobalID,hasAutoDoorOpener,isAccessibleToAllFloors,"
    "isKeyCardRequired,isAccessible,last_edited_date"
)


def main():
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        data = {k: fetch_layer(client, *SOURCES[k]) for k in ("buildings", "entrances")}
        data["legacy_entrances"] = fetch_layer(
            client, "Entrances_PNTS", FIELDS, object_id_field="OBJECTID_1"
        )
    now = datetime.now(UTC).isoformat()
    observations = read_door_observations(ROOT / "data/reviews/entrance-observations.json")
    updates, audits = [], {}
    for name in ("buildings", "residence_buildings"):
        path = ROOT / f"data/{name}.json"
        catalog, audit = supplement(json.loads(path.read_text(encoding="utf-8")), data, now)
        catalog = apply_door_observations(catalog, observations)
        updates.append((path, catalog))
        audits[name] = audit
    # Fetch and validate every input before replacing any previously usable data.
    atomic_json(ROOT / "data/entrance_evidence.json", {
        "observed_at": now,
        "source_url": "https://www.arcgis.com/home/item.html?id=88ffb7cddec243b9b6cebe80ccde1416",
        "current_map_entrances": len(data["entrances"]),
        "historical_entrances": len(data["legacy_entrances"]),
        "note": "Collection time is not field confirmation. Older evidence only fills gaps.",
        "records": data["legacy_entrances"], "audit": audits,
    })
    for path, catalog in updates:
        atomic_json(path, catalog)
    for name, audit in audits.items():
        added = [r for r in audit if r["decision"] == "added_dated_entrance"]
        print(name, "added dated powered entrances:", len(added))
        for row in added:
            print(row["building_name"], row["entrance_id"], row["source_record_date"])


if __name__ == "__main__":
    main()
