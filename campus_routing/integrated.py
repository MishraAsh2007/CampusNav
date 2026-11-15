"""Single service for routing and the Data API; serves a locally built map when present."""

import os
from pathlib import Path

from backend.main import app as data_app

from .api import create_app

ROOT = Path(__file__).resolve().parents[1]
app = create_app(
    data_app=data_app,
    graph_path=Path(os.getenv("ROUTING_GRAPH", ROOT / "data/umass-residences.graph.json")),
    buildings_path=Path(os.getenv("BUILDINGS_PATH", ROOT / "data/residence_buildings.json")),
)
