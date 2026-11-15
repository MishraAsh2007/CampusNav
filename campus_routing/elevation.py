"""Build-time Open Topo Data client with a resumable, per-dataset disk cache."""

import json
import math
import time
from pathlib import Path

import httpx

from .graph import write_json

DEFAULT_ENDPOINT = "https://api.opentopodata.org/v1/ned10m"


def fetch_elevations(
    points: list[tuple[float, float]],
    cache_path: Path,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    client=None,
    pause: float = 1.1,
) -> dict[tuple[float, float], float | None]:
    """Points are (lat, lng); missing samples stay None. API failures preserve prior cache."""
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    values = cache.setdefault(endpoint, {})

    def key(point):
        return f"{point[0]:.7f},{point[1]:.7f}"

    unique = list(dict.fromkeys(points))
    pending = [p for p in unique if key(p) not in values or values[key(p)] is None]
    owned_client = client is None
    client = client or httpx.Client(timeout=45, follow_redirects=True)
    last_call = None
    try:
        for offset in range(0, len(pending), 100):
            if last_call is not None:
                time.sleep(max(0, pause - (time.monotonic() - last_call)))
            batch = pending[offset : offset + 100]
            last_call = time.monotonic()
            response = client.get(
                endpoint,
                params={
                    "locations": "|".join(key(p) for p in batch),
                    "interpolation": "bilinear",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "OK" or len(payload.get("results", [])) != len(batch):
                raise ValueError(f"Unexpected elevation response: {payload.get('status')}")
            for point, result in zip(batch, payload["results"], strict=True):
                value = result.get("elevation")
                if value is not None and (
                    not isinstance(value, (float, int)) or not math.isfinite(value)
                ):
                    raise ValueError("Non-finite elevation returned by provider")
                values[key(point)] = value
            write_json(cache_path, cache)
            print(
                f"Elevation samples: {min(offset + 100, len(pending))}/{len(pending)}", flush=True
            )
    finally:
        if owned_client:
            client.close()
    return {point: values.get(key(point)) for point in points}
