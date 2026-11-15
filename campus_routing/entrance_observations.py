"""Keep scoped peer door observations separate from refreshed map geometry."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import ContractModel, Coordinate


class DoorObservation(ContractModel):
    id: str
    building_id: str
    entrance_id: str
    floor_id: str
    position: Coordinate
    door_type: Literal["push-button", "automatic", "manual"]
    source: Literal["community_peer_report"]
    reported_on: date
    observed_on: date | None = None
    current_operation_verified: Literal[False] = False
    note: str = Field(min_length=30)


def read_door_observations(path: Path) -> list[DoorObservation]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["version"] != 1:
        raise ValueError("Unsupported entrance observation version")
    return [DoorObservation.model_validate(row) for row in payload["observations"]]


def matching_door_observation(observations, building_id, entrance):
    """Never transfer an observation by nearest point or a compass label."""
    matches = [
        row
        for row in observations
        if row.building_id == building_id
        and row.entrance_id == entrance["id"]
        and row.floor_id == str(entrance.get("level"))
        and abs(row.position.lat - entrance["lat"]) < 1e-7
        and abs(row.position.lng - entrance["lng"]) < 1e-7
    ]
    return max(matches, key=lambda row: row.reported_on) if matches else None


def apply_door_observations(catalog, observations):
    result = deepcopy(catalog)
    for building in result["buildings"]:
        for entrance in building["entrances"]:
            record = matching_door_observation(observations, building["id"], entrance)
            if record is None:
                continue
            entrance["door_type"] = record.door_type
            entrance["door_evidence"] = record.model_dump(mode="json")
            entrance["current_operation_verified"] = False
            entrance["notes"] = (
                f"Door equipment confirmed by a peer, relayed {record.reported_on}: " + record.note
            )
        # Keep the shared entrance objects and their summary consistent without
        # promoting unknown step-free access from an opener observation.
        if "step_free_entrances" in building:
            by_id = {e["id"]: e for e in building["entrances"]}
            building["step_free_entrances"] = [
                by_id.get(e["id"], e) for e in building["step_free_entrances"]
            ]
    return result
