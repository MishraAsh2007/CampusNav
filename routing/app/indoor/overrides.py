"""Loads data/indoor_overrides.json and finds a building's entry by id, alias or name."""
from __future__ import annotations

import json
import re
from typing import Optional

from .. import config

_cache: dict = {"mtime": None, "path": None, "data": {}}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def load() -> dict:
    path = config.INDOOR_OVERRIDES_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != mtime or _cache["path"] != path:
        try:
            data = json.loads(path.read_text(encoding="utf-8")).get("buildings", {})
        except (OSError, ValueError):
            data = {}
        _cache.update(mtime=mtime, path=path, data=data)
    return _cache["data"]


def find_building(building_id: Optional[str], name: Optional[str] = None) -> Optional[dict]:
    keys = {_norm(building_id or ""), _norm(name or "")} - {""}
    for key, entry in load().items():
        names = {_norm(key)} | {_norm(a) for a in entry.get("aliases", [])}
        if keys & names:
            return entry
    return None
