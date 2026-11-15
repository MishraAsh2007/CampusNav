"""Check and install CampusNav's MongoDB collection validators."""

import argparse
import os
from copy import deepcopy
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


ENTRANCE_FLAGS = (
    "automatic_door", "hasAutoDoorOpener", "isAccessibleToAllFloors", "IsKeyCardRequired",
)
ENTRANCE = object_schema({
    **COORDINATES,
    "name": NONEMPTY_STRING,
    "step_free": {"bsonType": ["bool", "null"]},
    **{flag: {"bsonType": ["bool", "null"]} for flag in ENTRANCE_FLAGS},
}, optional=ENTRANCE_FLAGS, allow_extra=False)
INDOOR_LOCATION_FIELDS = {
    "location": NONEMPTY_STRING,
    **{name: {**bounds, "bsonType": [*NUMBER, "null"]} for name, bounds in COORDINATES.items()},
}
ELEVATOR = object_schema(INDOOR_LOCATION_FIELDS, optional=("lat", "lng"), allow_extra=False)
BATHROOM = object_schema({
    **INDOOR_LOCATION_FIELDS,
    "transfer_type": {"bsonType": ["string", "null"], "minLength": 1},
}, optional=("lat", "lng"), allow_extra=False)
OFFICIAL_NOTICE = object_schema({
    **CLOSURE_FIELDS,
    "id": NONEMPTY_STRING,
    "title": NONEMPTY_STRING,
    "description": {"bsonType": ["string", "null"], "minLength": 1},
    "location": object_schema(COORDINATES),
    "source": {"enum": ["official"]},
    "end_time": {"bsonType": ["date", "null"]},
}, optional=("radius", "status", "details", "description", "location", "last_updated"))

SCRAPED_OFFICIAL_NOTICE = object_schema({
    **CLOSURE_FIELDS,
    "id": NONEMPTY_STRING,
    "source_id": NONEMPTY_STRING,
    "source": {"enum": ["official"]},
    "status": {"enum": ["closed", "degraded"]},
    "end_time": {"bsonType": ["date", "null"]},
}, optional=("details", "last_updated"))

SCRAPED_REVIEW_REPORT = object_schema({
    "id": NONEMPTY_STRING,
    "source_id": NONEMPTY_STRING,
    "source": {"enum": ["official", "community", "publisher"]},
    "review_status": {"enum": ["needs_review"]},
    "routing_eligible": {"enum": [False]},
    "expires_at": {"bsonType": "date"},
})


def scraper_capture_schema(kind, record_schema):
    return object_schema({
        "_id": {"bsonType": "string", "pattern": f"^{kind}:.+"},
        "kind": {"enum": [kind]},
        "source_id": NONEMPTY_STRING,
        "observed_at": {"bsonType": "date"},
        "records": {"bsonType": "array", "items": record_schema},
    }, allow_extra=False)


SCHEMAS = {
    "Buildings": object_schema({
        **COORDINATES,
        "_id": {"bsonType": "string", "pattern": r"^[a-z0-9]+(-[a-z0-9]+)*$"},
        "name": NONEMPTY_STRING,
        "elevator_count": {"bsonType": ["int", "long", "null"], "minimum": 0},
        "entrances": {"bsonType": "array", "items": ENTRANCE},
        "elevators": {"bsonType": "array", "items": ELEVATOR},
        "bathrooms": {"bsonType": "array", "items": BATHROOM},
    }, optional=("elevators", "bathrooms"), allow_extra=False),
    "OfficialClosures": {"anyOf": [
        object_schema({
            "_id": {"enum": ["umass-service-interruptions"]},
            "closures": {"bsonType": "array", "items": OFFICIAL_NOTICE},
        }),
        scraper_capture_schema("official", SCRAPED_OFFICIAL_NOTICE),
    ]},
    "CommunityReports": {"anyOf": [
        object_schema({
            **CLOSURE_FIELDS,
            "_id": NONEMPTY_STRING,
            "source": {"enum": ["community"]},
            "end_time": {"bsonType": "date"},
            "title": {"bsonType": ["string", "null"]},
        }, optional=("radius", "status", "title", "details", "last_updated")),
        scraper_capture_schema("public", SCRAPED_REVIEW_REPORT),
    ]},
}


def add_nullable(field):
    bson_type = field.get("bsonType")
    if isinstance(bson_type, str):
        bson_type = [bson_type]
    if bson_type and "null" not in bson_type:
        field["bsonType"] = [*bson_type, "null"]


def extend_scraper_validator(name, current):
    if not current or current == {"$jsonSchema": SCHEMAS[name]}:
        return current
    if name == "Buildings":
        updated = deepcopy(current)
        properties = updated.get("$jsonSchema", {}).get("properties", {})
        add_nullable(properties.get("elevator_count", {}))
        entrances = properties.get("entrances", {}).get("items", {}).get("properties", {})
        add_nullable(entrances.get("step_free", {}))
        return updated

    kind, record_schema = (
        ("official", SCRAPED_OFFICIAL_NOTICE)
        if name == "OfficialClosures"
        else ("public", SCRAPED_REVIEW_REPORT)
    )
    capture_rule = {"$jsonSchema": scraper_capture_schema(kind, record_schema)}
    if set(current) == {"$or"}:
        alternatives = current["$or"]
        return current if capture_rule in alternatives else {"$or": [*alternatives, capture_rule]}
    return {"$or": [current, capture_rule]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Install validators after checking existing data")
    parser.add_argument(
        "--scraper-imports", action="store_true",
        help="Extend deployed validators for scraper imports while preserving existing rules",
    )
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
            if args.scraper_imports:
                validators = {}
                for name in SCHEMAS:
                    info = next(db.list_collections(filter={"name": name}))
                    current = info.get("options", {}).get("validator", {})
                    updated = extend_scraper_validator(name, current)
                    if updated != current:
                        validators[name] = updated
                if not validators:
                    print("No validator changes are needed for scraper imports.")
                    return
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
                    options = {} if args.scraper_imports else {
                        "validationLevel": "strict", "validationAction": "error",
                    }
                    db.command("collMod", name, validator=validator, **options)
                    print(f"{name}: validator installed")
    except PyMongoError as error:
        code = getattr(error, "code", None)
        parser.exit(1, f"MongoDB schema setup failed ({type(error).__name__}, code {code}).\n")


if __name__ == "__main__":
    main()
