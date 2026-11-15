"""Geometry helpers: haversine, bearings, nearest-node snapping, edge geometry."""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
M_PER_FT = 0.3048

LatLon = tuple[float, float]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing (0 = north, clockwise) from point 1 to point 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff_deg(a: float, b: float) -> float:
    """Signed smallest turn from bearing a to bearing b, in (-180, 180]. Positive = right."""
    d = (b - a + 180) % 360 - 180
    return 180.0 if d == -180 else d


_COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def compass_name(bearing: float) -> str:
    return _COMPASS[int(((bearing % 360) + 22.5) // 45) % 8]


def m_to_ft(m: float) -> float:
    return m / M_PER_FT


# --------------------------------------------------------------------------
# Point-to-polyline distance (local equirectangular projection, fine at campus scale)
# --------------------------------------------------------------------------
def _project(coords: Iterable[LatLon], ref_lat: float, ref_lon: float) -> np.ndarray:
    k_lat = math.pi / 180 * EARTH_RADIUS_M
    k_lon = k_lat * math.cos(math.radians(ref_lat))
    return np.array([[(lon - ref_lon) * k_lon, (lat - ref_lat) * k_lat] for lat, lon in coords])


def point_to_polyline_m(lat: float, lon: float, coords: Sequence[LatLon]) -> float:
    """Shortest distance in meters from a point to a polyline of (lat, lon) vertices."""
    if len(coords) == 1:
        return haversine_m(lat, lon, *coords[0])
    pts = _project(coords, lat, lon)  # point sits at the origin
    a, b = pts[:-1], pts[1:]
    ab = b - a
    denom = np.einsum("ij,ij->i", ab, ab)
    denom = np.where(denom == 0, 1e-12, denom)
    t = np.clip(-np.einsum("ij,ij->i", a, ab) / denom, 0.0, 1.0)
    closest = a + ab * t[:, None]
    return float(np.sqrt((closest ** 2).sum(axis=1)).min())


# --------------------------------------------------------------------------
# Graph helpers
# --------------------------------------------------------------------------
def node_latlon(G, n) -> LatLon:
    d = G.nodes[n]
    return float(d["y"]), float(d["x"])


def edge_coords(G, u, v, data: dict) -> list[LatLon]:
    """Edge geometry as [(lat, lon), ...] oriented from u to v."""
    geom = data.get("geometry")
    if geom is None:
        return [node_latlon(G, u), node_latlon(G, v)]
    pts = [(lat, lon) for lon, lat in geom.coords]
    ulat, ulon = node_latlon(G, u)
    if haversine_m(ulat, ulon, *pts[0]) > haversine_m(ulat, ulon, *pts[-1]):
        pts.reverse()
    return pts


def _node_index(G):
    idx = G.graph.get("_node_index")
    if idx is None:
        ids = np.array(list(G.nodes))
        lats = np.array([G.nodes[n]["y"] for n in ids], dtype=float)
        lons = np.array([G.nodes[n]["x"] for n in ids], dtype=float)
        idx = (ids, lats, lons)
        G.graph["_node_index"] = idx
    return idx


def invalidate_node_index(G) -> None:
    G.graph.pop("_node_index", None)


def nearest_node(G, lat: float, lon: float) -> tuple[int, float]:
    """Snap a coordinate to the closest graph node. Returns (node_id, distance_m)."""
    ids, lats, lons = _node_index(G)
    k_lat = math.pi / 180 * EARTH_RADIUS_M
    k_lon = k_lat * math.cos(math.radians(lat))
    d2 = ((lats - lat) * k_lat) ** 2 + ((lons - lon) * k_lon) ** 2
    i = int(d2.argmin())
    return int(ids[i]), float(math.sqrt(d2[i]))
