"""Apply reported car counts without treating GIS lobby points as individual cars."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from pydantic import Field

from .models import ContractModel


class ElevatorInventory(ContractModel):
    building_id: str
    total_count: int = Field(ge=1, le=100)
    reported_on: date
    source: str
    note: str


def apply_elevator_inventory(catalog, path: Path):
    if not path.exists():
        return catalog
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["version"] != 1:
        raise ValueError("Unsupported elevator inventory version")
    records = {row.building_id: row for row in (
        ElevatorInventory.model_validate(value) for value in payload["observations"]
    )}
    result = deepcopy(catalog)
    for building in result["buildings"]:
        record = records.get(building["id"])
        if record and isinstance(building.get("elevators"), dict):
            building["elevators"]["total_count"] = record.total_count
            building["elevators"]["count_evidence"] = record.model_dump(mode="json")
            # Leave operating counts, served-floor geometry and GIS positions untouched.
    return result
