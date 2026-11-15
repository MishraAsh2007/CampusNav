"""Fetch node elevations and compute signed per-edge grade (percent).

Providers (set ELEVATION_PROVIDER):
  epqs          USGS 3DEP via the Elevation Point Query Service: 1 m lidar on campus (default).
                One slow request per point; prefill with scripts/fetch_3dep.py.
  opentopodata  USGS NED 10 m via OpenTopoData (fast, batches of 100, but blurs short slopes)
  openmeteo     Copernicus 90 m DEM (coarse; only a fallback, grades will be noisy)

Elevations are cached per provider, keyed by OSM node id (data/elevation_cache.json for
opentopodata, data/elevation_cache_<provider>.json otherwise), so a rebuild of the same area
never hits the network again.

Bridges and tunnels are treated as level: the DEMs are bare-earth, so a footbridge would
otherwise appear to dip into whatever is below it.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Sequence

import requests

from .. import config

LatLon = tuple[float, float]
BATCH = 100
TIMEOUT_S = 30


def _get_json(url: str, params: dict, retries: int = 4) -> dict:
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT_S)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"elevation request failed: {url}: {last}")


def _opentopodata(coords: Sequence[LatLon]) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for i in range(0, len(coords), BATCH):
        chunk = coords[i : i + BATCH]
        locs = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in chunk)
        data = _get_json(config.OPENTOPODATA_URL, {"locations": locs})
        out.extend(r.get("elevation") for r in data["results"])
        time.sleep(1.1)  # public API: max 1 request / second
    return out


def _epqs_one(coord: LatLon) -> Optional[float]:
    lat, lon = coord
    data = _get_json(
        config.EPQS_URL,
        {"x": f"{lon:.6f}", "y": f"{lat:.6f}", "wkid": 4326, "units": "Meters", "includeDate": "false"},
    )
    val = data.get("value")
    if val is None or float(val) < -1000:  # EPQS uses -1000000 for "no data"
        return None
    return float(val)


def epqs_point(coord: LatLon) -> Optional[float]:
    """One EPQS lookup that never raises (the service is slow and times out now and then)."""
    try:
        return _epqs_one(coord)
    except RuntimeError:
        return None


def _epqs(coords: Sequence[LatLon]) -> list[Optional[float]]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(epqs_point, coords))


def _openmeteo(coords: Sequence[LatLon]) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for i in range(0, len(coords), BATCH):
        chunk = coords[i : i + BATCH]
        data = _get_json(
            config.OPENMETEO_URL,
            {
                "latitude": ",".join(f"{lat:.6f}" for lat, _ in chunk),
                "longitude": ",".join(f"{lon:.6f}" for _, lon in chunk),
            },
        )
        out.extend(data["elevation"])
    return out


PROVIDERS = {"opentopodata": _opentopodata, "epqs": _epqs, "openmeteo": _openmeteo}


def fetch_elevations(coords: Sequence[LatLon], provider: Optional[str] = None) -> list[Optional[float]]:
    """Elevation in meters for each (lat, lon); None where the provider has no data."""
    name = provider or config.ELEVATION_PROVIDER
    if name not in PROVIDERS:
        raise ValueError(f"unknown elevation provider {name!r}; choose from {sorted(PROVIDERS)}")
    return PROVIDERS[name](coords)


def cache_path_for(provider: Optional[str] = None) -> Path:
    name = provider or config.ELEVATION_PROVIDER
    if name == "opentopodata":
        return config.ELEVATION_CACHE_PATH
    return config.DATA_DIR / f"elevation_cache_{name}.json"


def write_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    tmp.replace(path)


def _load_cache(path: Path) -> dict[str, float]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _fill_missing(G) -> int:
    """Give nodes without elevation the mean of their neighbors (or the global mean)."""
    known = {n: d["elevation"] for n, d in G.nodes(data=True) if d.get("elevation") is not None}
    if not known:
        raise RuntimeError("no elevation data at all; check network / provider")
    global_mean = sum(known.values()) / len(known)
    missing = [n for n in G.nodes if G.nodes[n].get("elevation") is None]
    for n in missing:
        neigh = [known[m] for m in set(G.successors(n)) | set(G.predecessors(n)) if m in known]
        G.nodes[n]["elevation"] = sum(neigh) / len(neigh) if neigh else global_mean
    return len(missing)


def compute_edge_grades(G) -> None:
    """Set signed ``grade`` and ``grade_abs`` (percent) on every directed edge."""
    clamp = config.GRADE_CLAMP_PCT
    for u, v, _k, data in G.edges(keys=True, data=True):
        length = float(data.get("length") or 0.0)
        if length <= 0:
            grade = 0.0
        elif data.get("level_structure"):
            grade = 0.0  # bridge or tunnel: the bare-earth DEM doesn't see the deck
        else:
            rise = G.nodes[v]["elevation"] - G.nodes[u]["elevation"]
            grade = max(-clamp, min(clamp, rise / length * 100.0))
        data["grade"] = round(grade, 2)
        data["grade_abs"] = round(abs(grade), 2)


def add_elevation(G, cache_path: Optional[Path] = None, provider: Optional[str] = None):
    """Attach ``elevation`` to nodes and ``grade``/``grade_abs`` to edges (in place)."""
    cache_path = cache_path or cache_path_for(provider)
    cache = _load_cache(cache_path)
    todo = [n for n in G.nodes if str(n) not in cache]
    if todo:
        coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in todo]
        print(f"[elevation] fetching {len(todo)} nodes ({len(G) - len(todo)} cached)...")
        for n, elev in zip(todo, fetch_elevations(coords, provider)):
            if elev is not None:
                cache[str(n)] = float(elev)
        write_cache(cache_path, cache)

    for n in G.nodes:
        G.nodes[n]["elevation"] = cache.get(str(n))
    filled = _fill_missing(G)
    if filled:
        print(f"[elevation] {filled} nodes had no data; filled from neighbors")
    compute_edge_grades(G)
    return G
