"""Check and install CampusNav's MongoDB collection validators."""

import argparse
import os
from pathlib import Path
from sys import float_info

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

NUMBER = ["double", "int", "long"]
NONEMPTY_STRING = {"bsonType": "string", "minLength": 1}
COORDINATES = {
    "lat": {"bsonType": NUMBER, "minimum": -90, "maximum": 90},
    "lng": {"bsonType": NUMBER, "minimum": -180, "maximum": 180},
}
INDOOR_REFERENCES = {
    field: {"bsonType": ["string", "null"], "pattern": r"\S"}
    for field in ("building_id", "asset_id", "floor_id")
}
CLOSURE_FIELDS = {
    **COORDINATES,
    "radius": {
        "bsonType": NUMBER, "minimum": 0, "exclusiveMinimum": True, "maximum": float_info.max,
    },
    "type": {"enum": ["elevator", "ramp", "path", "construction"]},
    "status": {"enum": ["closed"]},
    "start_time": {"bsonType": "date"},
    "last_confirmed": {"bsonType": "date"},
    "last_updated": {"bsonType": "date"},
    "details": {"bsonType": ["string", "null"]},
}


def object_schema(
    properties: dict, *, optional: tuple[str, ...] = (), allow_extra: bool = True
) -> dict:
    return {
        "bsonType": "object",
        "required": [name for name in properties if name not in optional],
        "properties": properties,
        "additionalProperties": allow_extra,
    }


def with_indoor_references(schema: dict) -> dict:
    return {
        **schema,
        "properties": {**schema["properties"], **INDOOR_REFERENCES},
        "anyOf": [
            {"properties": {"floor_id": {"bsonType": "null"}}},
            {"required": ["building_id"], "properties": {"building_id": {"bsonType": "string"}}},
        ],
    }


ENTRANCE_FLAGS = (
    "automatic_door", "hasAutoDoorOpener", "isAccessibleToAllFloors", "IsKeyCardRequired",
)
ENTRANCE = object_schema({
    **COORDINATES,
    "id": {"bsonType": ["string", "null"], "pattern": r"\S"},
    "name": NONEMPTY_STRING,
    "step_free": {"bsonType": ["bool", "null"]},
    **{flag: {"bsonType": ["bool", "null"]} for flag in ENTRANCE_FLAGS},
}, optional=("id", *ENTRANCE_FLAGS), allow_extra=False)
INDOOR_LOCATION_FIELDS = {
    "location": NONEMPTY_STRING,
    **{name: {**bounds, "bsonType": [*NUMBER, "null"]} for name, bounds in COORDINATES.items()},
}
ELEVATOR = with_indoor_references(
    object_schema(INDOOR_LOCATION_FIELDS, optional=("lat", "lng"), allow_extra=False)
)
BATHROOM = with_indoor_references(object_schema({
    **INDOOR_LOCATION_FIELDS,
    "transfer_type": {"bsonType": ["string", "null"], "minLength": 1},
}, optional=("lat", "lng"), allow_extra=False))
OFFICIAL_PROVENANCE = {
    **{
        field: {"bsonType": ["date", "null"]}
        for field in ("ingested_at", "published_at", "snapshot_observed_at")
    },
    **{
        field: {"bsonType": ["string", "null"]}
        for field in ("source_ref", "source_id", "confirmation_kind")
    },
    "snapshot_fallback": {"bsonType": ["bool", "null"]},
}
OFFICIAL_NOTICE = with_indoor_references(object_schema({
    **CLOSURE_FIELDS,
    **OFFICIAL_PROVENANCE,
    "id": NONEMPTY_STRING,
    "title": NONEMPTY_STRING,
    "description": {"bsonType": ["string", "null"], "minLength": 1},
    "location": object_schema(COORDINATES),
    "source": {"enum": ["official"]},
    "status": {"enum": ["closed", "degraded"]},
    "end_time": {"bsonType": ["date", "null"]},
    "last_confirmed": {"bsonType": ["date", "null"]},
    "last_updated": {"bsonType": ["date", "null"]},
}, optional=(
    "radius", "status", "details", "description", "location", "last_updated", *OFFICIAL_PROVENANCE,
)))

SCHEMAS = {
    "Buildings": object_schema({
        **COORDINATES,
        "_id": {"bsonType": "string", "pattern": r"^[a-z0-9]+([-_][a-z0-9]+)*$"},
        "name": NONEMPTY_STRING,
        "elevator_count": {"bsonType": ["int", "long"], "minimum": 0},
        "entrances": {"bsonType": "array", "items": ENTRANCE},
        "elevators": {"bsonType": "array", "items": ELEVATOR},
        "bathrooms": {"bsonType": "array", "items": BATHROOM},
    }, optional=("elevators", "bathrooms"), allow_extra=False),
    "OfficialClosures": object_schema({
        "_id": {"enum": ["umass-service-interruptions"]},
        "closures": {"bsonType": "array", "items": OFFICIAL_NOTICE},
    }),
    "CommunityReports": with_indoor_references(object_schema({
        **CLOSURE_FIELDS,
        "_id": NONEMPTY_STRING,
        "source": {"enum": ["community", "app"]},
        "end_time": {"bsonType": "date"},
        "title": {"bsonType": ["string", "null"]},
        "description": {"bsonType": ["string", "null"]},
    }, optional=("radius", "status", "title", "description", "details", "last_updated"))),
}


def create_closure_indexes(db) -> None:
    db["CommunityReports"].create_index(
        [("building_id", 1), ("asset_id", 1), ("floor_id", 1)],
        name="indoor_closure_reference",
        partialFilterExpression={"building_id": {"$type": "string"}},
    )
    db["OfficialClosures"].create_index(
        [("closures.building_id", 1), ("closures.asset_id", 1), ("closures.floor_id", 1)],
        name="indoor_closure_reference",
        partialFilterExpression={"closures.building_id": {"$type": "string"}},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Install validators and indexes after checking existing data")
    args = parser.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        parser.exit(1, "Set MONGODB_URI in backend/.env or the environment.\n")
    try:
        with MongoClient(uri, timeoutMS=10000) as client:
            db = client[os.environ.get("MONGODB_DB", "campusnav")]
            existing = set(db.list_collection_names())
            missing = SCHEMAS.keys() - existing
            if missing:
                parser.exit(1, f"Start the Atlas backend to initialize: {', '.join(sorted(missing))}.\n")

            validators = {name: {"$jsonSchema": schema} for name, schema in SCHEMAS.items()}
            violations = {
                name: db[name].count_documents({"$nor": [validator]})
                for name, validator in validators.items()
            }
            for name, count in violations.items():
                print(f"{name}: {count} invalid documents")
            if any(violations.values()):
                parser.exit(1, "Correct the existing documents before applying validators.\n")
            if args.apply:
                for name, validator in validators.items():
                    db.command(
                        "collMod", name, validator=validator,
                        validationLevel="strict", validationAction="error",
                    )
                    print(f"{name}: validator installed")
                create_closure_indexes(db)
                print("Indoor closure indexes installed")
    except PyMongoError as error:
        code = getattr(error, "code", None)
        parser.exit(1, f"MongoDB schema setup failed ({type(error).__name__}, code {code}).\n")


if __name__ == "__main__":
    main()
