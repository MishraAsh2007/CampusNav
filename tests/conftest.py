import json
from pathlib import Path

import pytest

from campus_routing.indoor import IndoorMap


@pytest.fixture
def historical_ilc_mechanics():
    """Isolated OLD graph for algorithm tests, never evidence of campus accuracy.

    Production data must remain draft. Restoring this snapshot in memory keeps
    protocol/closure regressions independent of withdrawn campus geometry.
    """
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "data/indoor/ilc.json").read_text())
    archive = json.loads((root / "data/reviews/ilc-field-review.json").read_text())
    entrance_ids = {n["id"] for n in archive["original_entrance_nodes"]}
    raw["nodes"] = [n for n in raw["nodes"] if n["id"] not in entrance_ids]
    raw["nodes"].extend(archive["original_entrance_nodes"])
    raw["edges"].extend(archive["withdrawn_edges"])
    raw["portals"] = archive["withdrawn_portals"]
    raw.update(
        status="reviewed",
        reviewed_at="2026-11-14T00:00:00Z",
        name="UNVERIFIED historical ILC mechanics test fixture",
        review_notes="TEST ONLY: approval flag exercises routing mechanics, not real access.",
    )
    return IndoorMap.model_validate(raw)
