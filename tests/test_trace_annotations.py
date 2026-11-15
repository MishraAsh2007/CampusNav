import pytest
from pydantic import ValidationError

from campus_notices.trace_annotations import PlanTrace


def candidate(**updates):
    return PlanTrace(
        **(
            dict(
                id="a",
                source_id="drawing",
                page=1,
                floors=["2"],
                kind="corridor",
                points=[(1, 2), (3, 4)],
                coordinate_system="pdf_points",
                evidence="Visible corridor candidate; review outstanding.",
            )
            | updates
        )
    )


def test_unknown_measurement_stays_unknown_and_cannot_be_reviewed():
    assert candidate().length_m is None
    with pytest.raises(ValidationError, match="measurement evidence"):
        candidate(length_m=5)
    with pytest.raises(ValidationError, match="documented length and access"):
        candidate(status="reviewed")


def test_documented_measurement_and_access_are_required_for_review():
    assert (
        candidate(
            length_m=5,
            measurement_evidence="Measured plan dimension A–B",
            access="resident_only",
            status="reviewed",
        ).status
        == "reviewed"
    )
    with pytest.raises(ValidationError, match="finite"):
        candidate(points=[(float("nan"), 2), (3, 4)])
