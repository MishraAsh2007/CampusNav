"""Central configuration for the routing engine.

Everything tunable lives here so teammates can tweak penalties without
touching algorithm code. Secrets / overrides come from environment
variables (see .env.example at the repo root).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# routing/ directory and repo root
ROUTING_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ROUTING_DIR.parent

# Load .env from repo root first, then routing/ (later file wins only if unset).
load_dotenv(REPO_ROOT / ".env")
load_dotenv(ROUTING_DIR / ".env")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
DATA_DIR = ROUTING_DIR / "data"
MOCKS_DIR = ROUTING_DIR / "mocks"
GRAPH_PATH = Path(os.getenv("GRAPH_PATH", DATA_DIR / "graph.graphml"))
ELEVATION_CACHE_PATH = DATA_DIR / "elevation_cache.json"
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"
INDOOR_OVERRIDES_PATH = DATA_DIR / "indoor_overrides.json"

# --------------------------------------------------------------------------
# Area of interest: UMass Amherst central campus
# (ILC, Campus Center, Goodell, Du Bois Library, Southwest / Central dorms)
# --------------------------------------------------------------------------
BBOX = {
    "north": _float("BBOX_NORTH", 42.3965),
    "south": _float("BBOX_SOUTH", 42.3820),
    "east": _float("BBOX_EAST", -72.5180),
    "west": _float("BBOX_WEST", -72.5360),
}

# --------------------------------------------------------------------------
# Grade (slope) handling
# --------------------------------------------------------------------------
DEFAULT_MAX_GRADE_PCT = _float("DEFAULT_MAX_GRADE_PCT", 5.0)  # ADA comfortable sidewalk slope
MAX_GRADE_PCT_LIMIT = 30.0  # request validation ceiling

# Edges whose |grade| exceeds the user's max are blocked. DEM noise on very short
# edges can fake steep slopes, so edges shorter than this are only penalized.
MIN_HARD_BLOCK_LENGTH_M = _float("MIN_HARD_BLOCK_LENGTH_M", 8.0)
# Computed grades are clamped to this to avoid absurd DEM artefacts.
GRADE_CLAMP_PCT = 40.0
# Grades above SOFT_START * max_grade start getting a growing penalty.
GRADE_SOFT_START_FRACTION = 0.6
GRADE_SOFT_PENALTY = 2.0  # extra cost multiplier reached at exactly max grade

# --------------------------------------------------------------------------
# Penalty weights (cost = length_m * multiplier; multipliers are always >= 1
# so the haversine A* heuristic stays admissible)
# --------------------------------------------------------------------------
STEP_PENALTY_MULTIPLIER = 25.0  # used only if avoid_steps is false in accessible mode
CROSSING_PENALTY_MULTIPLIER = 1.0

# --------------------------------------------------------------------------
# Destination look-ahead (choosing which entrance to route to)
# --------------------------------------------------------------------------
# An elevator_out closure with no elevator coordinates to match counts for a building
# if it lies within this distance of the building's center point.
DEST_BUILDING_MATCH_M = _float("DEST_BUILDING_MATCH_M", 60.0)
# Extra slack when matching an elevator_out closure to an elevator's coordinates.
DEST_ELEVATOR_MATCH_SLACK_M = 10.0
# Warn if an entrance is this far from the nearest walkable graph node.
DEST_ENTRANCE_SNAP_WARN_M = 30.0

# --------------------------------------------------------------------------
# Snapping start/end points to the graph (see app/routing/snapping.py)
# --------------------------------------------------------------------------
# Points at least this far from their nearest node may be moved out of a dead end.
SNAP_RESNAP_MIN_M = _float("SNAP_RESNAP_MIN_M", 15.0)
# ...to a usable node at most this much farther away than the original snap.
SNAP_MAX_EXTRA_M = _float("SNAP_MAX_EXTRA_M", 40.0)
# Weight of the straight-line door-to-elevator distance when ranking entrances.
DEST_INDOOR_WEIGHT = 1.0
# Extra cost (meters) for an entrance with a reported door-opener problem
# (same values the map UI's usableEntrances() used).
DEST_DOOR_ISSUE_PENALTY_M = 120.0
DEST_DOOR_DEGRADED_PENALTY_M = 40.0
DEST_PUSH_BUTTON_PENALTY_M = 10.0

# --------------------------------------------------------------------------
# CampusNav backend (live closures and buildings); empty BACKEND_URL turns fetching off
# --------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").strip()
BACKEND_TIMEOUT_S = _float("BACKEND_TIMEOUT_S", 3.0)
BACKEND_CLOSURES_TTL_S = _float("BACKEND_CLOSURES_TTL_S", 5.0)
BACKEND_BUILDINGS_TTL_S = _float("BACKEND_BUILDINGS_TTL_S", 60.0)

# --------------------------------------------------------------------------
# Closures
# --------------------------------------------------------------------------
DEFAULT_CLOSURE_RADIUS_M = _float("DEFAULT_CLOSURE_RADIUS_M", 25.0)

# --------------------------------------------------------------------------
# Walking speeds for ETA (m/s)
# --------------------------------------------------------------------------
SPEED_STANDARD_MPS = 1.34
SPEED_ACCESSIBLE_MPS = 1.0

# --------------------------------------------------------------------------
# Elevation provider
# --------------------------------------------------------------------------
# epqs (USGS 3DEP, 1 m lidar on campus; default) | opentopodata (NED 10 m) | openmeteo (90 m, coarse)
ELEVATION_PROVIDER = os.getenv("ELEVATION_PROVIDER", "epqs")
OPENTOPODATA_URL = os.getenv("OPENTOPODATA_URL", "https://api.opentopodata.org/v1/ned10m")
EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
OPENMETEO_URL = "https://api.open-meteo.com/v1/elevation"
# Optional key for any paid/private elevation service you swap in.
ELEVATION_API_KEY = os.getenv("ELEVATION_API_KEY", "")

# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
