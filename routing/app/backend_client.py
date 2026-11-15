"""Reads live closures and buildings from the CampusNav backend (backend/main.py, MongoDB-backed).

The engine stays stateless: a request that carries its own closures or building uses those, and
only a request that leaves them out triggers a fetch. Results are cached for a few seconds so the
map's 15-second polling doesn't turn into a database query per click.

Set BACKEND_URL (default http://localhost:8000); leave it empty to turn fetching off.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from . import config

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def enabled() -> bool:
    return bool(config.BACKEND_URL)


def _get_json(path: str, ttl: float) -> tuple[Optional[Any], Optional[str]]:
    """(data, error). Fresh cache wins; on failure a stale copy is not used (outage data must be current)."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(path)
        if hit and now - hit[0] < ttl:
            return hit[1], None
    url = config.BACKEND_URL.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=config.BACKEND_TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
    with _lock:
        _cache[path] = (now, data)
    return data, None


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def get_closures(provided: Optional[list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], str, Optional[str]]:
    """-> (closures, source, error). source: request | backend | unavailable | none.

    ``provided`` None means "not sent": fetch GET /closures. An empty list is a real answer
    ("no closures") and is used as is.
    """
    if provided is not None:
        return provided, "request", None
    if not enabled():
        return [], "none", None
    data, err = _get_json("/closures", config.BACKEND_CLOSURES_TTL_S)
    if data is None or not isinstance(data, list):
        return [], "unavailable", err or "unexpected response"
    return data, "backend", None


def normalize_building(b: dict[str, Any]) -> dict[str, Any]:
    """Backend building -> engine building. An entrance whose step-free status is unknown counts as not step-free."""
    out = dict(b)
    out["entrances"] = [{**e, "step_free": bool(e.get("step_free"))} for e in b.get("entrances") or []]
    return out


def get_building(*ids: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """First backend building whose id matches any of ``ids`` (case-insensitive) -> (building, error)."""
    if not enabled():
        return None, None
    data, err = _get_json("/buildings", config.BACKEND_BUILDINGS_TTL_S)
    if not isinstance(data, list):
        return None, err
    by_id = {str(b.get("id", "")).lower(): b for b in data if isinstance(b, dict)}
    for i in ids:
        if i and str(i).lower() in by_id:
            return normalize_building(by_id[str(i).lower()]), None
    return None, None
