import pytest

from campus_notices.plan_integrity import REVIEWED_HASHES, require_reviewed_source


def test_new_plan_edition_does_not_silently_reuse_old_geometry():
    require_reviewed_source("707-06.pdf", REVIEWED_HASHES["707-06.pdf"])
    with pytest.raises(ValueError, match="re-inspect"):
        require_reviewed_source("707-06.pdf", "a" * 64)
    with pytest.raises(ValueError, match="re-inspect"):
        require_reviewed_source("unreviewed-plan.pdf", "a" * 64)
