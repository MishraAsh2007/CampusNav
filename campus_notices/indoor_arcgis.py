"""Public UMass indoor landmark references; points never imply walkable connections."""

import hashlib
import json

from campus_routing.models import Coordinate

BASE = "https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/"
GIS_SOURCES = {
    "umass-restrooms": dict(
        url=BASE + "Restrooms/FeatureServer/0",
        fields="OBJECTID,BuildingName,FLOOR,RoomName,ADA,DESCRIPTION,Transfer",
        where="BuildingName IN ('DuBois Library','Integrative Learning Center')",
    ),
    "umass-study-spaces": dict(
        url=BASE + "Campus_Buildings_StudentStudySpaces_View/FeatureServer/0",
        fields="OBJECTID,Title,Floor,RoomNumber,OtherRooms",
        where="Title LIKE 'Integrative Learning Center:%' OR Title LIKE 'DuBois Library:%'",
    ),
}
BUILDINGS = {"DuBois Library": "library", "Integrative Learning Center": "ilc"}


def feature_page(payload):
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Invalid public map response")
    if not isinstance(payload.get("features"), list):
        raise ValueError("Public map did not return feature records")
    reference = payload.get("spatialReference")
    if not isinstance(reference, dict) or reference.get("wkid") != 4326:
        raise ValueError("Expected geographic coordinates from public map")
    if type(payload.get("exceededTransferLimit", False)) is not bool:
        raise ValueError("Invalid public map pagination indicator")
    for feature in payload["features"]:
        if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
            raise ValueError("Invalid public feature attributes")
        if not isinstance(feature.get("geometry"), dict):
            raise ValueError("Missing public feature position")
        if type(feature["attributes"].get("OBJECTID")) is not int:
            raise ValueError("Invalid public feature ID")
    return payload["features"]


def parse_features(key, payload, observed_at):
    features = feature_page(payload)
    if payload.get("exceededTransferLimit"):
        raise ValueError("Incomplete public map response")
    rows, seen = [], set()
    for feature in features:
        attrs, point = feature.get("attributes", {}), feature.get("geometry", {})
        oid = attrs.get("OBJECTID")
        if oid is None or oid in seen:
            raise ValueError("Missing or duplicate public feature ID")
        seen.add(oid)
        if key == "umass-restrooms":
            name, floor, room = attrs.get("BuildingName"), attrs.get("FLOOR"), attrs.get("RoomName")
            label, kind = f"Restroom {room}", "restroom_reference"
        else:
            title = attrs.get("Title")
            if not isinstance(title, str):
                raise ValueError("Missing source building title")
            name = title.split(":", 1)[0]
            floor, room = attrs.get("Floor"), attrs.get("RoomNumber")
            label, kind = f"Study space {room}", "study_space_reference"
        if name not in BUILDINGS or not isinstance(room, str) or not room.strip():
            raise ValueError("Unknown building/room in filtered source")
        if floor is not None and not isinstance(floor, str):
            raise ValueError("Unexpected floor label")
        position = Coordinate(lat=point.get("y"), lng=point.get("x"))
        if not (42.37 <= position.lat <= 42.41 and -72.55 <= position.lng <= -72.50):
            raise ValueError("Landmark outside the UMass pilot area")
        rows.append(
            dict(
                id=hashlib.sha256(f"{key}|{oid}".encode()).hexdigest()[:20],
                building_id=BUILDINGS[name],
                floor_label=floor,
                label=label,
                room_id=room,
                kind=kind,
                position=position.model_dump(),
                source_id=key,
                source_url=GIS_SOURCES[key]["url"],
                source_feature_id=oid,
                observed_at=observed_at.isoformat(),
                routing_eligible=False,
                review_status="needs_topology_review",
                source_attributes=attrs,
                public_access=False
                if "staff" in str(attrs.get("DESCRIPTION") or "").lower()
                else None,
                review_notes="Source point and explicit floor only; not a doorway or corridor. "
                "Access, floor-label correspondence and walkable connections need review. "
                "Room numbers never determine floors.",
            )
        )
    if not rows:
        raise ValueError("No landmark records; retain previous data for review")
    return rows


def fetch_references(key, client, observed_at):
    config = GIS_SOURCES[key]
    features, seen = [], set()
    for _ in range(10):
        params = dict(
            f="json",
            where=config["where"],
            outFields=config["fields"],
            outSR=4326,
            returnGeometry="true",
            orderByFields="OBJECTID",
            resultRecordCount=200,
            resultOffset=len(features),
        )
        with client.stream(
            "GET", config["url"] + "/query", params=params, follow_redirects=False
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 5 * 1024 * 1024:
                    raise ValueError("Public map response too large")
        payload = json.loads(content)
        page = feature_page(payload)
        if not page and payload.get("exceededTransferLimit"):
            raise ValueError("Empty page in incomplete public map response")
        for feature in page:
            oid = feature.get("attributes", {}).get("OBJECTID")
            if oid is None or oid in seen:
                raise ValueError("Repeated public map page or missing feature ID")
            seen.add(oid)
            features.append(feature)
        if not payload.get("exceededTransferLimit"):
            return parse_features(
                key, dict(features=features, spatialReference={"wkid": 4326}), observed_at
            )
    raise ValueError("Public map pagination limit exceeded")
