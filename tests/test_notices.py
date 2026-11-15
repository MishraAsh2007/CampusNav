import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from campus_notices.cache import read_snapshot, snapshot_status
from campus_notices.gemini import GeminiError, GeminiParser
from campus_notices.models import Extraction, Impact, Notice
from campus_notices.pipeline import refresh
from campus_notices.rules import parse_rules
from campus_notices.sources import (
    SourceError,
    _table_notices,
    clean_text,
    extract_html,
    load_source,
    local_datetime,
)
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine
from campus_routing.models import RouteRequest
from scripts.make_demo import make_demo_graph

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def notice(text="The east elevator is out of service.", **overrides):
    return Notice.model_validate(
        {
            "id": "test:1",
            "source_id": "test",
            "source_ref": "fixture",
            "building": "Demo Center",
            "text": text,
            "observed_at": NOW,
            "start_time": NOW - timedelta(hours=1),
            "end_time": NOW + timedelta(hours=2),
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The east elevator is out of service.", "closed"),
        ("The east elevator is not working.", "closed"),
        ("The north ramp is blocked.", "closed"),
        ("The sidewalk will be closed.", "closed"),
        ("The east elevator is back in service.", "working"),
        ("The path has reopened.", "working"),
        ("The path will be reopened.", None),
        ("The path is not closed.", "working"),
        ("The elevator has intermittent service.", "degraded"),
        ("State elevator inspection. Car(s) may be unavailable during the test.", "degraded"),
        ("The east elevator is closed. The elevator is back in service.", None),
        ("The elevator is not out of service.", None),
        ("The elevator will not be closed.", None),
        ("The elevator might be closed.", None),
        ("Only one elevator will be closed at a time.", None),
        ("The elevator is closed daily from 8 to 9.", None),
        ("The elevator is closed; the ramp is blocked.", None),
        ("Elevator inspection is scheduled. The water supply will be shut down.", None),
        ("The elevator room has a broken water pipe.", None),
    ],
)
def test_rules_and_abstention(text, expected):
    result = parse_rules(notice(text)).extraction
    if expected is None:
        assert result is None
    else:
        assert result.impacts[0].status == expected


def test_irrelevant_utilities_and_explicit_times():
    assert not parse_rules(notice("Hot water service is interrupted.")).extraction.relevant
    parsed = parse_rules(
        notice(
            "The elevator is closed from 2026-11-14T10:00:00-05:00 to 2026-11-14T15:00:00-05:00.",
            start_time=None,
            end_time=None,
        )
    ).extraction
    assert parsed.impacts[0].start_time.hour == 10
    assert parse_rules(notice(start_time=None, end_time=None)).extraction is None


def test_dates_dst_and_no_invented_midnight():
    assert local_datetime("2026-07-01", "8:00 am").hour == 12
    assert local_datetime("2026-11-14", "8:00 AM").hour == 13
    with pytest.raises(ValueError):
        local_datetime("2026-11-14", "")
    with pytest.raises(ValueError):
        local_datetime("2026-11-01", "1:30 am")


def test_export_duplicate_document_numbers_and_contact_exclusion():
    headers = ["DOC ID#", "Building", "Starts", "Start Time", "Ends", "End Time", "Desc", "Phone"]
    row = [
        1,
        "Demo Center",
        "2026-11-14",
        "8 AM",
        "2026-11-14",
        "9 AM",
        "The east elevator is closed.",
        "413-555-0123",
    ]
    different = [1, "Other Center", *row[2:]]
    rows = _table_notices([headers, row, row, different], "export", "test.xlsx", NOW)
    assert len(rows) == 2
    assert rows[0].id != rows[1].id
    assert "413-555-0123" not in rows[0].model_dump_json()
    assert rows[0].observed_at == NOW


def test_html_excludes_navigation_and_rejects_login():
    assert (
        extract_html(b"<nav>Menu</nav><main>Elevator closed.</main><script>evil()</script>")
        == "Elevator closed."
    )
    with pytest.raises(SourceError, match="sign-in"):
        extract_html(b"<main>Sign in to your account</main>")
    assert "a@example.edu" not in clean_text("Contact a@example.edu or 413-555-0123")


def test_url_auth_redirect_does_not_become_empty_success():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"Location": "https://login.example.org"})
        )
    ) as client:
        with pytest.raises(SourceError, match="sign-in"):
            load_source(
                {"id": "web", "kind": "url", "url": "https://www.umass.edu/notice"},
                base=ROOT,
                now=NOW,
                client=client,
            )


@pytest.fixture
def setup(tmp_path):
    source_path = tmp_path / "notices.json"
    output = tmp_path / "official_snapshot.json"
    registry = tmp_path / "locations.json"
    locations = json.loads((ROOT / "examples/role3/locations.json").read_text())
    locations[0]["synthetic"] = False  # Test-only registry with explicitly provided coordinates.
    registry.write_text(json.dumps(locations))
    sources = [{"id": "test", "kind": "json", "path": str(source_path)}]

    def run(items=None, **kwargs):
        if items is not None:
            source_path.write_text(json.dumps([n.model_dump(mode="json") for n in items]))
        return refresh(
            sources=sources, base=tmp_path, registry_path=registry, output=output, now=NOW, **kwargs
        )

    return run, output, registry


def test_rules_publish_without_calling_gemini_and_route_reroutes(setup):
    run, _, _ = setup

    class NeverCall:
        def extract(self, *args):
            pytest.fail("Unambiguous notice must not call Gemini")

    snapshot = run([notice()], extractor=NeverCall())
    assert snapshot.counts["active"] == 1
    assert snapshot.closures[0].parser == "rules"
    engine = RoutingEngine(make_demo_graph())
    request = RouteRequest(
        start={"lat": 42.391, "lng": -72.528},
        end={"lat": 42.392, "lng": -72.528},
        closures=snapshot.closures,
    )
    assert engine.route(request, now=NOW).properties.total_distance == 242.83


def test_ambiguous_calls_fallback_once(setup):
    run, _, _ = setup

    class Fallback:
        calls = 0

        def extract(self, item, candidates):
            self.calls += 1
            return Extraction(
                relevant=True,
                reason="Parsed ambiguity",
                impacts=[
                    Impact(
                        type="elevator",
                        status="degraded",
                        evidence=item.text,
                        start_time=item.start_time,
                        end_time=item.end_time,
                    )
                ],
            )

    parser = Fallback()
    snapshot = run([notice("The east elevator could have reduced service.")], extractor=parser)
    assert parser.calls == 1
    assert snapshot.closures[0].parser == "gemini"


def test_missing_location_is_reviewed_without_inventing_coordinates(setup):
    run, output, registry = setup
    registry.write_text("[]")
    snapshot = run([notice()])
    assert snapshot.closures == []
    assert snapshot.counts["review"] == 1
    assert snapshot_status(output, NOW)["status"] == "needs_review"


def test_gemini_failure_preserves_last_known_snapshot_and_freshness(setup):
    run, output, _ = setup
    run([notice()])
    previous = output.read_bytes()

    class Broken:
        def extract(self, *args):
            raise GeminiError("Simulated API outage")

    with pytest.raises(GeminiError):
        run([notice("The east elevator might be closed.")], extractor=Broken())
    assert output.read_bytes() == previous
    status = snapshot_status(output, NOW)
    assert status["last_attempt"]["status"] == "failed"
    assert status["stale"]
    assert read_snapshot(output).closures[0].last_confirmed == NOW


def test_unresolved_revision_retains_previous_and_restoration_clears_it(setup):
    run, _, _ = setup
    run([notice()])
    unresolved = run([notice("The east elevator might be closed.")])
    assert len(unresolved.closures) == 1
    restored = run([notice("The east elevator is back in service.", id="test:2")])
    assert restored.closures == []


def test_hallucinated_evidence_and_location_are_quarantined(setup):
    run, _, _ = setup

    class Bad:
        def extract(self, item, candidates):
            return Extraction(
                relevant=True,
                reason="Bad output",
                impacts=[
                    Impact(
                        type="elevator",
                        status="closed",
                        location_id="invented",
                        evidence="This was never in the source",
                        start_time=item.start_time,
                        end_time=item.end_time,
                    )
                ],
            )

    result = run([notice("The east elevator might be closed.")], extractor=Bad())
    assert result.closures == []
    assert result.counts["review"] == 1


def test_gemini_content_cache_and_schema_validation(tmp_path):
    result = Extraction(relevant=False, reason="No accessibility impact")
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=result.model_dump_json())

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    parser = GeminiParser(
        "test-only", model="test-model", cache_path=tmp_path / "cache.json", client=client
    )
    parser.extract(notice(), [])
    parser.extract(notice(observed_at=NOW + timedelta(hours=1)), [])
    assert len(calls) == 1
    assert parser.cache_hits == 1
    assert calls[0]["config"].response_mime_type == "application/json"


def test_future_restoration_does_not_clear_current_outage(setup):
    run, _, _ = setup
    run([notice()])
    future = notice(
        "The east elevator is back in service.",
        start_time=NOW + timedelta(hours=1),
        end_time=NOW + timedelta(hours=3),
    )
    result = run([future])
    assert len(result.closures) == 1
    assert result.counts["restored"] == 0
    assert result.counts["review"] == 1


def test_missing_source_preserves_snapshot(setup):
    run, output, _ = setup
    run([notice()])
    previous = output.read_bytes()
    (output.parent / "notices.json").unlink()
    with pytest.raises(FileNotFoundError):
        run()
    assert output.read_bytes() == previous


def test_restoration_does_not_cancel_a_future_scheduled_outage(setup):
    run, _, _ = setup
    future = notice(start_time=NOW + timedelta(days=2), end_time=NOW + timedelta(days=3))
    run([future])
    result = run([notice("The east elevator is back in service.", id="separate-restoration")])
    assert len(result.closures) == 1
    assert result.closures[0].start_time == NOW + timedelta(days=2)


def test_blank_pdf_is_not_treated_as_no_outages():
    from io import BytesIO

    from pypdf import PdfWriter

    from campus_notices.sources import extract_pdf

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    data = BytesIO()
    writer.write(data)
    with pytest.raises(SourceError, match="OCR"):
        extract_pdf(data.getvalue())


def test_api_serves_cache_with_no_network_and_reports_missing_data(setup, tmp_path):
    run, output, _ = setup
    # Use a broad interval so this HTTP test does not depend on wall-clock time.
    run(
        [
            notice(
                start_time=datetime(2020, 1, 1, tzinfo=UTC),
                end_time=datetime(2099, 1, 1, tzinfo=UTC),
                observed_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        ]
    )
    with TestClient(create_app(RoutingEngine(make_demo_graph()), official_path=output)) as client:
        response = client.get("/official-closures")
        assert response.status_code == 200
        assert response.headers["X-Closures-Stale"] == "true"
        assert len(response.json()) == 1
        assert response.json()[0]["source"] == "official"
    with TestClient(
        create_app(RoutingEngine(make_demo_graph()), official_path=tmp_path / "missing.json")
    ) as client:
        assert client.get("/official-closures").status_code == 503
        assert client.get("/official-closures/status").json()["status"] == "unavailable"
