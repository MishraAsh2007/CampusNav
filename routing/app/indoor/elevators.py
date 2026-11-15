"""Which elevator cars in a building are out, given the active elevator_out closures.

Car count comes from data/indoor_overrides.json when the building has an entry (UMass GIS
and the map UI have one marker per lobby, not per car), otherwise from the building data.

A closure takes out:
  * every car      when scope is "all", or the building has one car and the notice can't say
  * the named cars when scope is "cars" (matched by car number)
  * one car        otherwise. If the closure sits at a lobby with a single free car, that car is
                   known to be out; if it can't be told apart (several cars, or no location), it
                   counts as one "unattributed" car and the others stay usable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import config
from ..schemas import Closure, ClosureType, DestinationBuilding, ElevatorStatus
from ..utils.geo import haversine_m
from ..routing.closures import _aware
from . import overrides

BANK_RADIUS_MAX_M = 30.0   # a closure this small is read as pointing at one lobby
_OUT_WORDS = ("out_of_service", "out", "down")


@dataclass
class Car:
    label: str
    number: Optional[int] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    out: bool = False
    id: Optional[str] = None

    @property
    def bank(self):
        return None if self.lat is None else (round(self.lat, 5), round(self.lng, 5))


def _building_cars(b: DestinationBuilding) -> list[Car]:
    cars = []
    for i, e in enumerate(b.elevators, 1):
        cars.append(Car(e.location or f"Elevator {i}", None, e.lat, e.lng, (e.status or "").lower() in _OUT_WORDS,
                        id=e.asset_id))
    return cars


def build_cars(b: DestinationBuilding) -> tuple[list[Car], str, int]:
    """(cars, count_source, flagged_out_unattributed)."""
    entry = overrides.find_building(b.id, b.name)
    spec = (entry or {}).get("elevators") or {}
    if spec.get("cars"):
        pos = spec.get("position") or {}
        cars = [Car(c.get("label") or c.get("id") or f"Elevator {i}", c.get("number"),
                    c.get("lat", pos.get("lat")), c.get("lng", pos.get("lng")), id=c.get("id"))
                for i, c in enumerate(spec["cars"], 1)]
        flagged = sum(1 for c in _building_cars(b) if c.out)
        return cars, "override", flagged
    cars = _building_cars(b)
    if spec.get("car_count") is not None:
        n = int(spec["car_count"])
        flagged = sum(1 for c in cars if c.out)
        cars = cars[:n] + [Car(f"Elevator {i}") for i in range(len(cars) + 1, n + 1)]
        # Flags from the building data stay attributed only when the list was used as is.
        return cars, "override", 0 if len(b.elevators) <= n else flagged
    if b.elevator_count is not None and b.elevator_count > len(cars):
        cars += [Car(f"Elevator {i}") for i in range(len(cars) + 1, b.elevator_count + 1)]
    return cars, "building", 0


@dataclass
class Assessment:
    cars: list[Car]
    status: ElevatorStatus
    working: list[tuple[float, float]]
    all_out: bool
    unattributed: int

    def bank_usable(self, car_ids: Optional[list[str]]) -> bool:
        """Is at least one car in the bank certainly running, whichever unknown cars are the ones out?

        ``car_ids`` None means the whole building. Unattributed outages could all be in this bank,
        so they are subtracted from its free cars.
        """
        if self.all_out:
            return False
        bank = [c for c in self.cars if car_ids is None or c.id in car_ids]
        return len([c for c in bank if not c.out]) - self.unattributed > 0


def evaluate(b: DestinationBuilding, active: list[Closure]) -> tuple[ElevatorStatus, list[tuple[float, float]]]:
    """Returns the status and the coordinates of cars that are (probably) working."""
    a = assess(b, active)
    return a.status, a.working


def assess(b: DestinationBuilding, active: list[Closure]) -> Assessment:
    cars, source, flagged_unattributed = build_cars(b)
    spec_banks = ((overrides.find_building(b.id, b.name) or {}).get("elevators") or {}).get("banks") or {}
    banks = {k: list(v.get("cars") or []) for k, v in spec_banks.items()}
    total = len(cars)
    all_out = False
    unattributed = flagged_unattributed
    matched: list[Closure] = []

    located = [c for c in cars if c.lat is not None]
    for c in sorted((c for c in active if c.type == ClosureType.elevator_out and c.lat is not None),
                    key=lambda c: c.id):
        # A closure that names a car or bank by its backend asset id needs no location match.
        if c.asset_id:
            car = next((k for k in cars if k.id == c.asset_id), None)
            if car is not None:
                car.out = True
                matched.append(c)
                continue
            if c.asset_id in banks:
                group = [k for k in cars if k.id in banks[c.asset_id]]
                free = [k for k in group if not k.out]
                matched.append(c)
                if len(free) == 1:
                    free[0].out = True
                elif free:
                    unattributed += 1
                continue
        near_car = [k for k in located
                    if haversine_m(c.lat, c.lon, k.lat, k.lng) <= c.radius_m + config.DEST_ELEVATOR_MATCH_SLACK_M]
        near_building = haversine_m(c.lat, c.lon, b.lat, b.lng) <= max(config.DEST_BUILDING_MATCH_M, c.radius_m)
        if not near_car and not near_building:
            continue
        matched.append(c)

        if c.scope == "all":
            all_out = True
        elif c.scope == "cars" and c.cars:
            for n in c.cars:
                car = next((k for k in cars if k.number == n), None)
                if car is None:
                    unattributed += 1
                else:
                    car.out = True
        elif total <= 1:
            all_out = True
        elif near_car and c.radius_m <= BANK_RADIUS_MAX_M:
            # Pointing at one lobby: take out a car there if exactly one is still free.
            nearest = min(near_car, key=lambda k: haversine_m(c.lat, c.lon, k.lat, k.lng))
            lobby = [k for k in cars if k.bank == nearest.bank]
            free = [k for k in lobby if not k.out]
            if len(free) == 1:
                free[0].out = True
            elif free:
                unattributed += 1
            else:
                pass  # lobby already fully out
        else:
            unattributed += 1

    known_out = [k for k in cars if k.out]
    possibly_out = total if all_out else min(total, len(known_out) + unattributed)
    free_cars = [k for k in cars if not k.out]
    working = [] if possibly_out >= total else [(k.lat, k.lng) for k in free_cars if k.lat is not None]
    stamps = [t for t in ((c.confirmed_at or c.reported_at) for c in matched) if t]
    status = ElevatorStatus(
        total=total,
        possibly_out=possibly_out,
        working=total - possibly_out,
        located=len(located),
        closure_ids=[c.id for c in matched],
        last_confirmed_at=max(_aware(t) for t in stamps) if stamps else None,
        count_source=source,
        out_cars=[k.label for k in known_out] if not all_out else [k.label for k in cars],
        unattributed_out=0 if all_out else min(unattributed, max(total - len(known_out), 0)),
    )
    return Assessment(cars, status, working, all_out, 0 if all_out else status.unattributed_out)
