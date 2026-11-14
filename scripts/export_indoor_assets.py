"""Merge reviewed, located indoor asset IDs into Role 3's outage matching registry."""

import argparse
import json
from pathlib import Path

from campus_notices.cache import atomic_json, writer_lock
from campus_notices.models import Location
from campus_routing.indoor import read_indoor


def export_assets(map_path, registry_path):
    data = read_indoor(map_path)
    if data.status != "reviewed" or data.synthetic:
        raise ValueError("Only reviewed, non-synthetic map assets can enter the notice registry")
    with writer_lock(registry_path):
        previous = (
            json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
        )
        locations = [Location.model_validate(r) for r in previous]
        merged = {r.id: r for r in locations}
        if len(merged) != len(locations):
            raise ValueError("Duplicate registry IDs")
        count = 0
        for asset in data.assets:
            if not asset.position:
                continue
            old = merged.get(asset.id)
            if old and old.building_id not in (None, data.building_id):
                raise ValueError("Asset ID already belongs to another building")
            merged[asset.id] = Location(
                id=asset.id,
                name=asset.label,
                type=asset.kind,
                **asset.position.model_dump(),
                radius=old.radius if old else 4,
                building_aliases=list(
                    dict.fromkeys(
                        [data.name, data.building_id, *(old.building_aliases if old else [])]
                    )
                ),
                asset_phrases=asset.aliases or [asset.label],
                reviewed=True,
                synthetic=False,
                asset_id=asset.id,
                building_id=data.building_id,
                evidence=f"Reviewed map {data.building_id}; source {asset.source_id}; "
                f"reviewed {data.reviewed_at.isoformat()}. {data.review_notes}",
            )
            count += 1
        atomic_json(registry_path, [row.model_dump(mode="json") for row in merged.values()])
        return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", type=Path)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/location_registry.json",
    )
    args = parser.parse_args()
    print(f"Exported {export_assets(args.map, args.registry)} located assets.")


if __name__ == "__main__":
    main()
