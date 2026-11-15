import json
from datetime import UTC, datetime

import pytest

from campus_notices.all_sources import assemble, inspect_stage, run_all, stages
from campus_notices.cache import atomic_json

NOW = datetime(2026, 11, 14, 18, tzinfo=UTC)


def quiet(*args, **kwargs):
    pass


def test_one_failed_worker_does_not_prevent_later_collection_or_refresh_cached_time(tmp_path):
    old = "2020-01-01T00:00:00+00:00"
    atomic_json(tmp_path / ".cache/residence-access.json", {"observed_at": old, "buildings": []})
    called = []

    def worker(stage, root, log):
        called.append(stage.id)
        if stage.id == "campus-map":
            return 1
        atomic_json(root / "data/library_elevator_sources.json", {"observed_at": NOW.isoformat()})
        return 0

    report = run_all(
        tmp_path,
        selected=["campus-map", "library-elevators"],
        executor=worker,
        progress=quiet,
        now=NOW,
    )
    assert called == ["campus-map", "library-elevators"]
    first = report["stages"][0]
    assert first["mode"] == "cache" and first["observed_at"] == old
    data = json.loads((tmp_path / "data/collected_data.json").read_text())
    assert data["campus_map"]["observed_at"] == old
    assert data["library_elevator_sources"]["observed_at"] == NOW.isoformat()


def test_offline_collection_never_calls_network_worker_and_separates_private_reports(tmp_path):
    atomic_json(tmp_path / "data/private/sharepoint-session.json", {"cookie": "SESSION_SECRET"})
    (tmp_path / ".env").write_text("KEY=API_SECRET")
    atomic_json(
        tmp_path / "data/private/external_reports.json",
        {
            "reports": [{"text": "PRIVATE_COMPLAINT", "status": "broken"}],
            "generated_at": "2020-01-01T00:00:00Z",
        },
    )
    atomic_json(
        tmp_path / "data/private/residence_floorplans/manifest.json",
        {"records": [{"name": "PRIVATE_PLAN.pdf"}], "observed_at": "2020-01-01T00:00:00Z"},
    )

    def forbidden(*args):
        pytest.fail("Offline collection invoked a worker")

    run_all(tmp_path, offline=True, executor=forbidden, progress=quiet, now=NOW)
    public = (tmp_path / "data/collected_data.json").read_text()
    private = (tmp_path / "data/private/collected_data.json").read_text()
    assert "PRIVATE_COMPLAINT" not in public and "PRIVATE_PLAN.pdf" not in public
    assert "PRIVATE_COMPLAINT" in private and "PRIVATE_PLAN.pdf" in private
    assert "SESSION_SECRET" not in public + private and "API_SECRET" not in public + private
    assert json.loads(public)["official_closures"] is None


def test_bundle_deduplicates_buildings_and_filters_expired_official_closures(tmp_path):
    for name in ("buildings", "residence_buildings"):
        atomic_json(
            tmp_path / f"data/{name}.json", {"buildings": [{"id": "library", "name": name}]}
        )
    closure = dict(
        id="test",
        notice_id="n",
        location_id="l",
        source_id="s",
        source_ref="https://example.com/notice",
        parser="rules",
        lat=42.39,
        lng=-72.53,
        radius=4,
        type="elevator",
        status="closed",
        source="official",
        last_confirmed="2026-11-14T10:00:00Z",
        start_time="2026-11-14T10:00:00Z",
    )
    atomic_json(
        tmp_path / "data/official_snapshot.json",
        {
            "generated_at": NOW.isoformat(),
            "closures": [
                dict(closure, end_time="2026-11-14T11:00:00Z"),
                dict(closure, id="active", end_time="2026-11-14T23:00:00Z"),
            ],
            "counts": {},
            "sources": ["s"],
            "source_observed_at": {"s": NOW.isoformat()},
        },
    )
    public, _ = assemble(tmp_path, [], NOW)
    assert len(public["buildings"]) == 1
    assert [c["id"] for c in public["official_closures"]] == ["active"]


def test_exit_zero_does_not_hide_source_fallback_or_unconfigured_feeds(tmp_path):
    atomic_json(
        tmp_path / "data/private/external_reports.json",
        {
            "sources": {"pvta": {"state": "live"}, "reddit": {"state": "not_configured"}},
            "reports": [],
        },
    )
    stage = next(s for s in stages() if s.id == "public-reports")
    status = inspect_stage(tmp_path, stage, exit_code=0, attempted_at=NOW.isoformat())
    assert status["mode"] == "partial"
    assert status["sources"]["reddit"]["state"] == "not_configured"


def test_synthetic_notices_cannot_enter_normal_combined_closures(tmp_path):
    atomic_json(
        tmp_path / "data/official_snapshot.json",
        {
            "synthetic": True,
            "generated_at": NOW.isoformat(),
            "closures": [],
            "counts": {},
            "sources": [],
            "source_observed_at": {},
        },
    )
    public, _ = assemble(tmp_path, [], NOW)
    assert public["official_closures"] is None


def test_metadata_file_with_all_sources_unavailable_is_not_usable_cached_data(tmp_path):
    atomic_json(
        tmp_path / "data/indoor_sources.json",
        {
            "sources": {"library": {"mode": "unavailable"}},
            "records": [],
        },
    )
    stage = next(s for s in stages() if s.id == "indoor-references")
    status = inspect_stage(tmp_path, stage, exit_code=0, attempted_at=NOW.isoformat())
    assert status["mode"] == "unavailable" and not status["available"]
