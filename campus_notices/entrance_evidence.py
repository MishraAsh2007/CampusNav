"""Supplement missing powered entrances with dated, public UMass GIS evidence.

Older records never override a nearby current-map door. Spatial ambiguity stays
in the audit instead of becoming an entrance. No indoor topology is inferred.
"""

from copy import deepcopy
from datetime import UTC, datetime

from shapely import transform
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from scripts.sync_campus_access import BUILDINGS, EXTRA_PARTS, PROJECT, SERVICE

PREFIX = "umass-legacy-entrance-"
LEGACY_URL = f"{SERVICE}/Entrances_PNTS/FeatureServer/0"


def metric_point(row):
    return Point(PROJECT(row["geometry"]["x"], row["geometry"]["y"]))


def source_date(milliseconds):
    if milliseconds is None:
        return "date unknown"
    return datetime.fromtimestamp(milliseconds / 1000, UTC).date().isoformat()


def supplement(catalog, source, observed_at):
    result = deepcopy(catalog)
    shapes = {}
    names = {}
    for feature in source["buildings"]:
        attrs = feature["attributes"]
        key = EXTRA_PARTS.get(str(attrs["BuildingID"]), str(attrs["BuildingID"]))
        poly = unary_union([Polygon(r).buffer(0) for r in feature["geometry"]["rings"]])
        poly = transform(poly, PROJECT, interleaved=False)
        shapes[key] = unary_union([shapes.get(key, poly), poly])
        names[key] = attrs["BuildingName"]
    by_key = {}
    for building in result["buildings"]:
        # Preserve all residences, manual additions and indoor identities.
        if building["category"] == "residential":
            continue
        key = next((k for k, spec in BUILDINGS.items() if spec[0] == building["id"]), None)
        if key:
            by_key[key] = building
            building["entrances"] = [
                e for e in building["entrances"] if not e["id"].startswith(PREFIX)
            ]
    current_points = [metric_point(row) for row in source["entrances"]]
    audit = []
    for feature in source["legacy_entrances"]:
        attrs = feature["attributes"]
        if attrs.get("hasAutoDoorOpener") != 1 or attrs.get("isKeyCardRequired") != 0:
            continue
        p = metric_point(feature)
        matches = sorted((shape.distance(p), key) for key, shape in shapes.items())
        oid = attrs["OBJECTID_1"]  # The service's real objectIdField, not OBJECTID.
        record = {"record_id": oid, "source_url": f"{LEGACY_URL}/{oid}",
                  "source_record_date": source_date(attrs.get("last_edited_date"))}
        if not matches or matches[0][0] > 10:
            audit.append(record | {"decision": "outside_footprints"})
            continue
        distance, key = matches[0]
        record |= {"building_code": key, "building_name": names[key],
                   "footprint_gap_m": round(distance, 2)}
        if len(matches) > 1 and matches[1][0] - distance <= 2:
            audit.append(record | {"decision": "ambiguous_building"})
            continue
        if any(p.distance(current) < 8 for current in current_points):
            audit.append(record | {"decision": "current_map_takes_precedence"})
            continue
        if key not in by_key:
            audit.append(record | {"decision": "outside_selected_nonresidential_catalog"})
            continue
        if attrs.get("isAccessible") == 0:
            audit.append(record | {"decision": "source_marks_inaccessible"})
            continue
        building = by_key[key]
        center = Point(PROJECT(building["location"]["lng"], building["location"]["lat"]))
        label = ("North" if p.y > center.y else "South") + (
            "east" if p.x > center.x else "west"
        ) + " entrance (historical GIS)"
        entry = dict(
            id=PREFIX + str(oid), name=label,
            lat=feature["geometry"]["y"], lng=feature["geometry"]["x"],
            step_free=True if attrs.get("isAccessible") == 1
            or attrs.get("isAccessibleToAllFloors") == 1 else None,
            door_type="push-button", keycard_required=False, has_ramp=None,
            in_routing_area=building["in_routing_area"],
            source="UMass public Entrances_PNTS (historical GIS)",
            source_url=record["source_url"],
            source_record_date=record["source_record_date"],
            source_observed_at=observed_at, current_operation_verified=False,
            notes=f"Door opener documented in a UMass GIS record dated "
            f"{record['source_record_date']}. Current operation and access are unverified; "
            "this record predates later building renovations.",
        )
        building["entrances"].append(entry)
        audit.append(record | {"decision": "added_dated_entrance", "entrance_id": entry["id"]})
    for building in by_key.values():
        building["step_free_entrances"] = [
            e for e in building["entrances"]
            if e.get("step_free") is True and not e.get("keycard_required")
        ]
        kinds = {e["door_type"] for e in building["step_free_entrances"]}
        building["door_type"] = next(iter(kinds)) if len(kinds) == 1 else (
            "mixed" if kinds else "unknown"
        )
    result["entrance_evidence_observed_at"] = observed_at
    return result, audit
