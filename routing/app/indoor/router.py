"""Indoor routing: entrance -> room/floor inside one building, step-free by default.

Reads the indoor maps in data/indoor/*.json (nodes, edges, portals; schema in
indoor-map.schema.json) and applies data/indoor_overrides.json on top:
  * entrance doors with their real floor (the ILC's "ground floor" doors open onto floor 2),
  * elevator cars, grouped into banks, so a bank is skipped only when none of its cars certainly runs,
  * floors that aren't public destinations.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import networkx as nx

from .. import config
from ..schemas import Closure, DestinationBuilding
from ..utils.geo import haversine_m, m_to_ft
from . import overrides
from .elevators import Assessment, assess

ENTRANCE_MATCH_M = 30.0        # a given outdoor door must be this close to an indoor door
UNVERIFIED_DOOR_PENALTY_M = 150.0
_SRC = "__entrance__"
_maps: dict = {"sig": None, "data": {}}


# ------------------------------------------------------------------ loading
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def load_maps() -> dict[str, dict]:
    """building_id -> indoor map dict (reloaded when a file changes)."""
    d = config.DATA_DIR / "indoor"
    files = [f for f in sorted(d.glob("*.json")) if not f.name.endswith(".schema.json")] if d.is_dir() else []
    sig = tuple((f.name, f.stat().st_mtime) for f in files)
    if _maps["sig"] != sig:
        out = {}
        for f in files:
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get("building_id"):
                out[m["building_id"]] = m
        _maps.update(sig=sig, data=out)
    return _maps["data"]


def find_map(building_id: Optional[str], name: Optional[str] = None) -> tuple[Optional[str], Optional[dict]]:
    keys = {_norm(building_id or ""), _norm(name or "")} - {""}
    maps = load_maps()
    for key, m in maps.items():
        ov = overrides.load().get(key, {})
        names = {_norm(key), _norm(m.get("name", ""))} | {_norm(a) for a in ov.get("aliases", [])}
        if keys & names:
            return key, m
    return None, None


# ----------------------------------------------------------- model building
@dataclass
class Door:
    id: str
    name: str
    node: str
    floor: str
    lat: Optional[float]
    lng: Optional[float]
    step_free: Optional[bool]       # None = not confirmed
    verified: Any = None
    note: Optional[str] = None


@dataclass
class Bank:
    asset_id: str
    label: str
    car_ids: Optional[list[str]]    # None = whole building
    usable: bool = True


@dataclass
class Model:
    key: str
    map: dict
    ov: dict
    G: nx.Graph
    doors: list[Door]
    banks: dict[str, Bank]
    nodes: dict[str, dict]
    floors: dict[str, dict]
    assessment: Assessment
    avoid_steps: bool
    warnings: list[str] = field(default_factory=list)


def _door_name(m: dict, nodes: dict, node_id: str) -> str:
    n = nodes.get(node_id) or {}
    return n.get("label") or node_id


def build_model(key: str, m: dict, active: list[Closure], avoid_steps: bool,
                building: Optional[DestinationBuilding]) -> Model:
    ov = overrides.load().get(key, {})
    nodes = {n["id"]: dict(n) for n in m["nodes"]}
    floors = {f["id"]: f for f in m["floors"]}
    ev = ov.get("elevators") or {}

    if building is None:
        pts = [(a["position"]["lat"], a["position"]["lng"]) for a in m.get("assets", []) if a.get("position")]
        pts = pts or [(c["lat"], c["lng"]) for c in ev.get("cars", []) if c.get("lat") is not None]
        lat = sum(p[0] for p in pts) / len(pts) if pts else 0.0
        lng = sum(p[1] for p in pts) / len(pts) if pts else 0.0
        building = DestinationBuilding(id=key, name=m.get("name", key), lat=lat, lng=lng)
    a = assess(building, active)

    # Banks: the map's elevator assets, regrouped by the override's cars when it has them.
    assets = {x["id"]: x for x in m.get("assets", []) if x.get("kind") == "elevator"}
    banks: dict[str, Bank] = {}
    spec_banks = ev.get("banks") or {}
    for asset_id in {e["asset_id"] for e in m["edges"] if e["kind"] == "elevator" and e.get("asset_id")}:
        sb = spec_banks.get(asset_id)
        label = (sb or {}).get("label") or (assets.get(asset_id) or {}).get("label") or asset_id
        banks[asset_id] = Bank(asset_id, label, (sb or {}).get("cars"))
        banks[asset_id].usable = a.bank_usable(banks[asset_id].car_ids)

    # Doors: scraper portals (minus the ones an override replaces) plus override doors.
    replaced = {d.get("replaces_portal") for d in (ov.get("entrance_floors") or {}).values() if isinstance(d, dict)}
    doors: list[Door] = []
    for p in m.get("portals", []):
        if p["id"] in replaced or p["indoor_node_id"] not in nodes:
            continue
        g = p["geometry"][0]
        n = nodes[p["indoor_node_id"]]
        doors.append(Door(p["id"], _door_name(m, nodes, p["indoor_node_id"]), p["indoor_node_id"],
                          n["floor_id"], g[1], g[0], p.get("step_free")))
    G = nx.Graph()
    for n in nodes.values():
        G.add_node(n["id"])
    for k, d in (ov.get("entrance_floors") or {}).items():
        if not isinstance(d, dict) or "connects_to" not in d or d.get("lat") is None:
            continue
        ct = d["connects_to"]
        if ct["node"] not in nodes:
            continue
        nodes[k] = {"id": k, "label": d.get("name") or k, "floor_id": d["floor"], "kind": "entrance", "x": None, "y": None}
        G.add_node(k)
        G.add_edge(k, ct["node"], w=float(ct["length_m"]), edge={
            "id": f"{k}-link", "start": k, "end": ct["node"], "kind": "corridor", "length_m": float(ct["length_m"]),
            "step_free": True, "public_access": True,
        })
        sf = d.get("step_free_approach", True)  # key absent: a door the team confirmed as an accessible entrance
        doors.append(Door(k, d.get("name") or k, k, d["floor"], d["lat"], d["lng"], sf, d.get("verified"), d.get("approach")))

    for e in m["edges"]:
        if e["start"] not in nodes or e["end"] not in nodes:
            continue
        if e.get("public_access") is False:
            continue
        if avoid_steps and (e["kind"] == "steps" or e.get("step_free") is False):
            continue
        w = float(e.get("length_m") or 0.0)
        if e["kind"] == "elevator":
            bank = banks.get(e.get("asset_id"))
            if bank is not None and not bank.usable:
                continue
        if G.has_edge(e["start"], e["end"]) and G[e["start"]][e["end"]]["w"] <= w:
            continue
        G.add_edge(e["start"], e["end"], w=w, edge=e)
    return Model(key, m, ov, G, doors, banks, nodes, floors, a, avoid_steps)


# --------------------------------------------------------------- destination
_ORD_RX = re.compile(r"^(?:floor|fl|level)?\s*(\d{1,2})(?:st|nd|rd|th)?\s*(?:floor|fl)?$", re.I)


def _floor_by_query(floors: dict[str, dict], q: str) -> Optional[str]:
    nq = _norm(q)
    for fid, f in floors.items():
        if nq in {_norm(fid), _norm(f.get("label", ""))} | {_norm(x) for x in f.get("aliases", [])}:
            return fid
    m = _ORD_RX.match(q.strip())
    if m:
        want = int(m.group(1))
        for fid, f in floors.items():
            digits = re.match(r"(\d+)", fid) or re.match(r"(\d+)", f.get("label", ""))
            if digits and int(digits.group(1)) == want:
                return fid
    return None


def resolve_destination(model: Model, room: Optional[str], floor: Optional[str], node_id: Optional[str]):
    """-> (node dict or None, message)."""
    nodes, floors = model.nodes, model.floors
    if node_id:
        n = nodes.get(node_id)
        return (n, "") if n else (None, f"No place with id {node_id!r} in {model.map.get('name')}.")
    cands = [n for n in nodes.values() if n["kind"] in ("room",) and n["id"] not in {d.node for d in model.doors}]
    if room:
        nq = _norm(room)
        exact = [n for n in cands if nq in {_norm(n["label"])} | {_norm(x) for x in n.get("aliases", [])}]
        if exact:
            return exact[0], ""
        fid = _floor_by_query(floors, room)
        if fid is not None:  # "2nd floor", "5": the whole floor, not a room that happens to mention it
            floor = fid
            room = None
    if room:
        want = _tokens(room) - {"room", "the"}
        hits = [n for n in cands if want and want <= _tokens(n["label"] + " " + " ".join(n.get("aliases", [])))]
        if floor:
            ff = _floor_by_query(floors, floor)
            hits = [n for n in hits if ff is None or n["floor_id"] == ff] or hits
        if hits:
            hits.sort(key=lambda n: len(n["label"]))
            return hits[0], ("" if len(hits) == 1 else f"{len(hits)} places match {room!r}; using {hits[0]['label']}.")
        fid = _floor_by_query(floors, room)
        if fid is None:
            return None, f"Couldn't find {room!r} in {model.map.get('name')}."
        floor = fid
    if floor:
        fid = _floor_by_query(floors, floor)
        if fid is None:
            return None, f"{model.map.get('name')} has no floor {floor!r}."
        # A whole floor means its lobby/main corridor, not a particular room or car stop (that car may be
        # the one that's out). Floors with no corridor node fall back to a room, then to an elevator stop.
        for kind in ("junction", "room", "elevator_stop"):
            spots = [n for n in nodes.values() if n["floor_id"] == fid and n["kind"] == kind
                     and n["id"] not in {d.node for d in model.doors}]
            if spots:
                return spots[0], ""
        return None, f"No mapped destination on floor {floors[fid].get('label', fid)}."
    return None, "Give a room, a floor or a node_id."


# ------------------------------------------------------------------ routing
@dataclass
class Found:
    door: Door
    path: list[str]
    total_m: float


def _door_extra(d: Door, avoid_steps: bool) -> Optional[float]:
    """Extra cost to prefer sure doors; None excludes the door."""
    if d.step_free is False:
        return None if avoid_steps else 0.0
    if d.step_free is None or d.verified == "partial":
        return UNVERIFIED_DOOR_PENALTY_M
    return 0.0


def _match_door(model: Model, lat: float, lng: float) -> Optional[Door]:
    best = None
    for d in model.doors:
        if d.lat is None:
            continue
        dist = haversine_m(lat, lng, d.lat, d.lng)
        if dist <= ENTRANCE_MATCH_M and (best is None or dist < best[0]):
            best = (dist, d)
    return best[1] if best else None


def find_route(model: Model, target: str, door: Optional[Door]) -> Optional[Found]:
    G = model.G.copy()
    allowed = [door] if door else model.doors
    G.add_node(_SRC)
    by_node: dict[str, Door] = {}
    for d in allowed:
        extra = _door_extra(d, model.avoid_steps)
        if extra is None and door is None:
            continue
        G.add_edge(_SRC, d.node, w=extra or 0.0, edge=None)
        by_node[d.node] = d
    if target not in G or not G.has_node(_SRC) or not by_node:
        return None
    try:
        total, path = nx.single_source_dijkstra(G, _SRC, target, weight="w")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    d = by_node[path[1]]
    extra = _door_extra(d, model.avoid_steps) or 0.0
    return Found(d, path[1:], total - extra)


# --------------------------------------------------------------- presentation
def _ft(m: float) -> int:
    return int(round(m_to_ft(m), -1)) if m >= 25 else int(round(m_to_ft(m)))


def _lc(label: str) -> str:
    return label[0].lower() + label[1:] if len(label) > 1 and label[1].islower() else label


def _floor_label(model: Model, fid: str) -> str:
    return model.floors.get(fid, {}).get("label", fid)


def build_legs(model: Model, found: Found, dest: dict, reverse: bool = False) -> tuple[list[dict], list[str]]:
    """Legs and text for found.path. With ``reverse`` the path runs room -> door (leaving the building)."""
    G, nodes = model.G, model.nodes
    legs: list[dict] = []
    steps: list[str] = []
    door = found.door
    goal = door.name if reverse else dest["label"]
    if reverse:
        steps.append(f"Start at {dest['label']} ({_floor_label(model, dest['floor_id'])}).")
    else:
        steps.append(f"Enter through the {door.name} (opens onto {_floor_label(model, door.floor)}).")

    def floor_meta(fid: str) -> dict:
        f = model.floors.get(fid, {})
        return {"floor": fid, "floor_label": f.get("label", fid), "coordinate_system": f.get("coordinate_system"),
                "image_url": f.get("image_url"), "image_width": f.get("image_width"),
                "image_height": f.get("image_height")}

    i = 0
    path = found.path
    while i < len(path) - 1:
        e = G[path[i]][path[i + 1]]["edge"]
        if e["kind"] == "elevator":
            asset = e.get("asset_id")
            j = i
            length = 0.0
            while j < len(path) - 1:
                ej = G[path[j]][path[j + 1]]["edge"]
                if ej["kind"] != "elevator" or ej.get("asset_id") != asset:
                    break
                length += float(ej.get("length_m") or 0)
                j += 1
            a, b = nodes[path[i]], nodes[path[j]]
            bank = model.banks.get(asset)
            label = bank.label if bank else "the elevator"
            leg = {"kind": "elevator", "bank": label, "from_floor": a["floor_id"], "to_floor": b["floor_id"],
                   "from_floor_label": _floor_label(model, a["floor_id"]),
                   "to_floor_label": _floor_label(model, b["floor_id"]), "length_m": round(length, 1),
                   "points": []}
            legs.append(leg)
            steps.append(f"Take the {_lc(label)} "
                         f"from {leg['from_floor_label']} to {leg['to_floor_label']}.")
            i = j
            continue
        # walk: consecutive non-elevator edges on one floor
        j = i
        length = 0.0
        fid = nodes[path[i]]["floor_id"]
        while j < len(path) - 1:
            ej = G[path[j]][path[j + 1]]["edge"]
            if ej["kind"] == "elevator" or nodes[path[j + 1]]["floor_id"] != fid:
                break
            length += float(ej.get("length_m") or 0)
            j += 1
        pts = [[nodes[n]["x"], nodes[n]["y"]] for n in path[i:j + 1] if nodes[n].get("x") is not None]
        end = nodes[path[j]]
        legs.append({"kind": "walk", **floor_meta(fid), "from": nodes[path[i]]["label"], "to": end["label"],
                     "length_m": round(length, 1), "points": pts})
        if length > 0:
            if end["kind"] == "elevator_stop":
                target = "the elevator"
                bank_next = None
                if j < len(path) - 1:
                    nxt = G[path[j]][path[j + 1]]["edge"]
                    bank_next = model.banks.get(nxt.get("asset_id"))
                if bank_next:
                    target = "the " + _lc(bank_next.label)
                steps.append(f"Walk about {_ft(length)} ft to {target}.")
            elif path[j] != path[-1]:
                steps.append(f"Walk about {_ft(length)} ft along {_floor_label(model, fid)}.")
            else:
                steps.append(f"Walk about {_ft(length)} ft to {goal}.")
        i = j
    if reverse:
        steps.append(f"Leave through the {door.name} ({_floor_label(model, door.floor)}).")
    else:
        steps.append(f"Arrive at {dest['label']} ({_floor_label(model, dest['floor_id'])}).")
    return legs, steps
