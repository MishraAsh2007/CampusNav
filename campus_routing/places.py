"""Resolve user-selected indoor locations without guessing a position from a floor."""

import re
from typing import Literal

from pydantic import Field, model_validator

from .models import ContractModel, Coordinate

PILOT_BUILDINGS = {
    "library": {
        "name": "W. E. B. Du Bois Library",
        "aliases": ["library", "du bois", "dubois", "w e b du bois library"],
    },
    "ilc": {
        "name": "Integrative Learning Center",
        "aliases": ["ilc", "integrative learning center", "integrated learning center"],
    },
}
ORDINALS = dict(
    zip(
        (
            "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
            "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth"
        ).split(),
        map(str, range(1, 21)),
        strict=True,
    )
)


def normalize(value):
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return re.sub(r"\b([ns])\s+(\d{3})\b", r"\1\2", value)


def contains(text, name):
    name = normalize(name)
    return bool(name and f" {name} " in f" {normalize(text)} ")


def floor_key(value):
    value = normalize(value)
    for word, number in ORDINALS.items():
        value = re.sub(rf"\b{word}\b", number, value)
    value = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", value)
    if value == "lower level":
        return "lower-level"
    value = re.sub(r"\b(?:floor|level)\b", "", value).strip()
    return str(int(value)) if value.isdigit() else value


def floors_in_text(text):
    value = normalize(text)
    for word, number in ORDINALS.items():
        value = re.sub(rf"\b{word}\b", number, value)
    matches = re.findall(
        r"\b(?:floor|level)\s+(\d+|ll|e)\b|"
        r"\b(\d+)(?:st|nd|rd|th)?\s+(?:floor|level)\b",
        value,
    )
    result = {floor_key(a or b) for a, b in matches}
    if "lower level" in value:
        result.add("lower-level")
    if "ground floor" in value:
        result.add("ground")
    return result


class LocationQuery(ContractModel):
    text: str = Field(default="", max_length=500)
    building_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    floor_id: str | None = Field(default=None, max_length=80)
    node_id: str | None = Field(default=None, max_length=150)
    outdoor: Coordinate | None = None

    @model_validator(mode="after")
    def exclusive_location(self):
        if self.outdoor and (self.text or self.building_id or self.floor_id or self.node_id):
            raise ValueError("Provide either an outdoor position or an indoor description")
        return self


class ResolveRequest(ContractModel):
    location: LocationQuery
    purpose: Literal["origin", "destination"] = "origin"


class PlaceResolver:
    def __init__(self, maps, sources, *, allow_synthetic=False):
        self.maps = maps
        self.sources = sources
        self.allow_synthetic = allow_synthetic
        self.buildings = dict(PILOT_BUILDINGS)
        for key, data in maps.items():
            self.buildings.setdefault(key, dict(name=data.name, aliases=[key.replace("-", " ")]))

    def coverage(self, building):
        data = self.maps.get(building)
        room_nodes = [node for node in data.nodes if node.kind == "room"] if data else []
        return dict(
            building_id=building,
            status=data.status if data else "not_mapped",
            routable=bool(
                data and data.status == "reviewed" and (not data.synthetic or self.allow_synthetic)
            ),
            room_routable=bool(
                data
                and data.status == "reviewed"
                and room_nodes
                and (not data.synthetic or self.allow_synthetic)
            ),
            synthetic=bool(data and data.synthetic),
            mapped_nodes=len(data.nodes) if data else 0,
            room_nodes=len(room_nodes),
            mapped_connections=len(data.edges) if data else 0,
            entrance_connections=len(data.portals) if data else 0,
        )

    def references(self, building):
        return [r for r in self.sources.get("records", []) if r["building_id"] == building]

    def floors(self, building):
        data = self.maps.get(building)
        result = {}
        for floor in data.floors if data else []:
            result[floor.id] = dict(id=floor.id, label=floor.label, aliases=floor.aliases)
        for record in self.references(building):
            labels = [record["floor_label"]] if record.get("floor_label") else []
            labels += record.get("floor_labels", [])
            for label in labels:
                key = floor_key(label)
                if not any(floor_key(f["label"]) == key for f in result.values()):
                    result[key] = dict(id=key, label=label, aliases=[])
        return list(result.values())

    def landmarks(self, building, floor_id=None):
        data = self.maps.get(building)
        if not data or not self.coverage(building)["routable"]:
            return []
        public_nodes = {n for e in data.edges if e.public_access for n in (e.start, e.end)}
        return [
            n
            for n in data.nodes
            if n.id in public_nodes and (not floor_id or n.floor_id == floor_id)
        ]

    def catalog(self):
        return dict(
            buildings=[
                dict(
                    id=key,
                    **info,
                    coverage=self.coverage(key),
                    floors=self.floors(key),
                    landmarks=[n.model_dump(mode="json") for n in self.landmarks(key)],
                    source_references=self.references(key),
                )
                for key, info in self.buildings.items()
            ],
            source_status=self.sources.get("sources", {}),
            note="Source records are routable through the explicit pilot topology, "
            "but room approaches require field verification before production "
            "accessibility claims.",
        )

    def resolve(self, query, *, purpose="origin", allow_building=False):
        if query is None:
            query = LocationQuery()
        if query.outdoor:
            return dict(
                status="resolved",
                endpoint=dict(
                    kind="outdoor",
                    **query.outdoor.model_dump(),
                ),
            )
        location = query.model_dump(mode="json", exclude_none=True)

        def ask(code, field, question, choices=(), **extra):
            return dict(
                status="needs_input",
                code=code,
                field=f"{purpose}.{field}",
                question=question,
                choices=list(choices),
                location=location,
                **extra,
            )

        mentions = {
            b
            for b, info in self.buildings.items()
            if any(contains(query.text, a) for a in [info["name"], *info["aliases"]])
        }
        if re.search(r"science|engineering", query.text, re.I):
            mentions.discard("library")  # A different library must not resolve to Du Bois.
        if query.building_id:
            mentions.add(query.building_id)
        if len(mentions) != 1 or not mentions.issubset(self.buildings):
            return ask(
                "choose_building",
                "building_id",
                "Which mapped building are you in or travelling to?",
                [dict(building_id=k, label=v["name"]) for k, v in self.buildings.items()],
            )
        building = mentions.pop()
        location["building_id"] = building
        coverage = self.coverage(building)
        floor_choices = self.floors(building)
        requested_floors = floors_in_text(query.text)
        if query.floor_id:
            requested_floors.add(floor_key(query.floor_id))
        floor_id = None
        if requested_floors:
            candidates = [
                f
                for f in floor_choices
                if requested_floors & {floor_key(a) for a in [f["id"], f["label"], *f["aliases"]]}
            ]
            if len(requested_floors) != 1 or len(candidates) != 1:
                return ask(
                    "choose_floor",
                    "floor_id",
                    "Which listed floor are you referring to?",
                    floor_choices,
                    coverage=coverage,
                )
            floor_id = candidates[0]["id"]
            location["floor_id"] = floor_id
        nodes = self.landmarks(building, floor_id)
        known = [
            r
            for r in self.references(building)
            if r["kind"] != "floor_plan"
            and any(
                contains(query.text, name)
                for name in [*re.split(r"[,;]", r["label"]), r.get("room_id") or ""]
            )
        ]
        known_ids = {r["id"] for r in known if r.get("public_access") is not False}
        if query.node_id:
            matched = [n for n in nodes if n.id == query.node_id]
        elif known_ids:
            # Prefer the source-directory match over generic building aliases such
            # as "ILC", which otherwise match every room in that building.
            matched = [
                n for n in nodes if known_ids.intersection(n.source_record_ids)
            ]
        else:
            matched = [
                n
                for n in nodes
                if any(contains(query.text, label) for label in [n.label, *n.aliases])
            ]
        if len(matched) == 1:
            node = matched[0]
            return dict(
                status="resolved",
                coverage=coverage,
                location=location,
                label=node.label,
                floor_id=node.floor_id,
                endpoint=dict(kind="indoor", building_id=building, node_id=node.id),
            )
        if len(matched) > 1:
            return ask(
                "ambiguous_landmark",
                "node_id",
                "Which of these locations do you mean?",
                [dict(node_id=n.id, floor_id=n.floor_id, label=n.label) for n in matched],
                coverage=coverage,
            )
        if known and not query.node_id:
            return dict(
                status="coverage_unavailable",
                code="landmark_not_mapped",
                location=location,
                coverage=coverage,
                source_references=known,
                message="This place is in the source directory, but its walkable "
                "connections have not been mapped and reviewed. No directions generated.",
            )
        # A building-only destination permits a trip to an outside entrance approach.
        # Any floor, room or unknown landmark phrase must not silently become that request.
        remainder = query.text
        for alias in sorted(
            [self.buildings[building]["name"], *self.buildings[building]["aliases"]],
            key=len,
            reverse=True,
        ):
            remainder = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", "", remainder, flags=re.I)
        remainder = re.sub(
            r"\b(?:to|the|please|go|take|me|at|in|i|am)\b", "", remainder, flags=re.I
        )
        if (
            allow_building
            and not requested_floors
            and not query.node_id
            and not normalize(remainder)
        ):
            return dict(
                status="resolved",
                endpoint=dict(kind="building", building_id=building),
                coverage=coverage,
            )
        if query.node_id and not coverage["routable"]:
            return dict(
                status="coverage_unavailable",
                code="indoor_not_ready",
                location=location,
                coverage=coverage,
                message="This building's indoor graph is not ready.",
            )
        return ask(
            "choose_landmark",
            "node_id",
            "Which room, entrance, or labeled elevator landing are you at? A floor alone "
            "does not identify your position."
            if purpose == "origin"
            else "Which room or mapped destination do you want to reach?",
            [dict(node_id=n.id, floor_id=n.floor_id, label=n.label) for n in nodes],
            coverage=coverage,
            message=None
            if coverage["routable"]
            else "Floor references exist, but there are no reviewed indoor routes here yet.",
        )
