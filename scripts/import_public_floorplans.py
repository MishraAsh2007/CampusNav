"""Register publicly available UMass indoor floor-plan sources.

This script records authoritative plan assets without inventing route geometry.
The indoor graph remains separate so a plan can be reviewed and traced before
its corridors, doors, and room approaches become routable.
"""

import argparse
import json
from pathlib import Path

from campus_notices.cache import atomic_json
from campus_routing.indoor import read_indoor

ROOT = Path(__file__).resolve().parents[1]

ILC_PLANS = {
    "1": {
        "label": "1st Floor",
        "url": (
            "https://tiles.arcgis.com/tiles/2gdL2gxYNFY2TOUb/arcgis/rest/services/"
            "Integrated_Learning_Center_First_Floor_Scaled/MapServer"
        ),
        "source_id": "ilc-floorplans",
        "format": "ArcGIS tiled map service",
    },
    "2": {
        "label": "2nd Floor",
        "url": (
            "https://tiles.arcgis.com/tiles/2gdL2gxYNFY2TOUb/arcgis/rest/services/"
            "Integrated_Learning_Center_Second_Floor_Reup/MapServer"
        ),
        "source_id": "ilc-floorplans",
        "format": "ArcGIS tiled map service",
    },
}


def build_manifest(source_path):
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    plans = []
    for row in payload.get("records", []):
        if row.get("kind") == "floor_plan":
            plans.append(
                {
                    "building_id": row["building_id"],
                    "floor_label": row["floor_label"],
                    "source_id": row["source_id"],
                    "url": row["image_url"],
                    "format": "PNG floor-plan image",
                    "geometry_status": "source plan available; topology not traced",
                }
            )
    for floor_id, row in ILC_PLANS.items():
        plans.append(
            {
                "building_id": "ilc",
                "floor_id": floor_id,
                "floor_label": row["label"],
                "source_id": row["source_id"],
                "url": row["url"],
                "format": row["format"],
                "geometry_status": "source plan available; topology not traced",
            }
        )
    return {
        "version": 1,
        "sources": {
            "library-floorplans": "https://umass.stackmap.com/explore/",
            "ilc-floorplans": (
                "https://www.arcgis.com/sharing/rest/search?"
                "q=%22Integrative%20Learning%20Center%22&f=pjson"
            ),
        },
        "plans": plans,
        "note": (
            "These are authoritative public plan assets. They are intentionally "
            "not treated as routable geometry until corridors, doorways, and "
            "vertical connections are traced and reviewed."
        ),
    }


def update_map_metadata(path, manifest):
    data = read_indoor(path).model_dump(mode="json")
    building_id = data["building_id"]
    building_plans = [p for p in manifest["plans"] if p["building_id"] == building_id]
    if not building_plans:
        return
    sources = {source["id"]: source for source in data["sources"]}
    if building_id == "ilc":
        sources.setdefault(
            "ilc-floorplans",
            {
                "id": "ilc-floorplans",
                "url": ILC_PLANS["1"]["url"],
                "edition": "Public UMass ArcGIS floor-plan layers",
                "observed_at": data["reviewed_at"],
            },
        )
    data["sources"] = list(sources.values())
    for floor in data["floors"]:
        candidates = [
            p
            for p in building_plans
            if p.get("floor_id") == floor["id"]
            or p.get("floor_label", "").casefold() == floor["label"].casefold()
        ]
        if candidates:
            floor["image_url"] = candidates[0]["url"]
            floor["source_id"] = candidates[0]["source_id"]
    data["review_notes"] = (
        data["review_notes"] + " Public floor-plan assets are registered; corridor and doorway "
        "topology still requires explicit tracing from those plans."
    )
    atomic_json(path, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=ROOT / "data/indoor_sources.json")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/indoor/public_floorplans.json"
    )
    parser.add_argument("--maps", type=Path, default=ROOT / "data/indoor")
    args = parser.parse_args()
    manifest = build_manifest(args.sources)
    atomic_json(args.manifest, manifest)
    update_map_metadata(args.maps / "library.json", manifest)
    update_map_metadata(args.maps / "ilc.json", manifest)
    print(args.manifest)


if __name__ == "__main__":
    main()
