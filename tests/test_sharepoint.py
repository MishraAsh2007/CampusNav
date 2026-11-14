import csv
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from campus_notices.cache import snapshot_status
from campus_notices.pipeline import refresh
from campus_notices.sharepoint import (
    OPTIONAL,
    REQUIRED,
    SITE,
    AuthenticationRequired,
    endpoints,
    load_sharepoint,
    read_session,
    scrape,
)
from campus_notices.sources import SourceError, load_source
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine
from scripts.make_demo import make_demo_graph

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
SPEC = {"id": "umass-maintenance", "kind": "sharepoint"}
PREFIX = endpoints(SPEC)[1]
FIELDS = [
    {"Title": title, "InternalName": title.replace(" ", "_x0020_").replace("#", "_x0023_")}
    for title in (*REQUIRED, *OPTIONAL)
]


def item(ident=1, text="The east elevator is out of service.", **changes):
    record = {
        "DOC ID#": ident,
        "Building": "Demo Center",
        "Starts": "2026-11-14T05:00:00Z",
        "Start Time": "6:00 AM",
        "Ends": "2026-11-14T05:00:00Z",
        "End Time": "10:00 AM",
        "Desc": text,
        **changes,
    }
    return {
        "Id": ident,
        **{field["InternalName"]: record.get(field["Title"], None) for field in FIELDS},
    }


def client_for(items=None, *, next_link=None, next_status=200):
    items = [item()] if items is None else items
    calls = []

    def handle(request):
        assert request.method == "GET"
        calls.append(request)
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json={"d": {"results": FIELDS}})
        if "$skiptoken" in request.url.params:
            if next_status != 200:
                return httpx.Response(next_status)
            return httpx.Response(200, json={"d": {"results": [item(2)]}})
        data = {"results": items}
        if next_link:
            data["__next"] = next_link
        return httpx.Response(200, json={"d": data})

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def unavailable(status=401):
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status)))


def export_file(tmp_path, **changes):
    path = tmp_path / "fallback.csv"
    row = item(**{"Starts": "11/14/2026", "Ends": "11/14/2026", **changes})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([f["Title"] for f in FIELDS])
        writer.writerow([row[f["InternalName"]] for f in FIELDS])
    old = (NOW - timedelta(hours=3)).timestamp()
    os.utime(path, (old, old))
    return path


def test_live_pagination_and_contact_redaction():
    client, calls = client_for(
        [item(text="The east elevator is out of service. Contact x@example.edu or 413-555-0123.")],
        next_link=PREFIX + "/items?$skiptoken=Paged%3DTRUE%26p_ID%3D1",
    )
    with client:
        result = scrape(SPEC, now=NOW, client=client)
    assert len(calls) == 3
    assert len(result) == 2
    assert result[0].start_time == datetime(2026, 11, 14, 11, tzinfo=UTC)
    assert result[0].observed_at == NOW
    assert "example.edu" not in result[0].text
    assert "555-0123" not in result[0].text
    assert "$expand" not in calls[1].url.params
    assert "Building" in calls[1].url.params["$select"]
    assert "Desc" in calls[1].url.params["$select"]


def test_live_succeeds_even_if_spreadsheet_is_missing(tmp_path):
    spec = {**SPEC, "fallback": {"kind": "xlsx", "path": "missing.xlsx"}}
    client, _ = client_for()
    with client:
        batch = load_sharepoint(spec, base=tmp_path, now=NOW, client=client)
    assert batch.state.mode == "live"
    assert len(batch.notices) == 1


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-07-03T04:00:00Z", datetime(2026, 7, 3, 10, tzinfo=UTC)),
        ("2026-11-14T05:00:00Z", datetime(2026, 11, 14, 11, tzinfo=UTC)),
        ("2026-11-15T00:00:00Z", datetime(2026, 11, 14, 11, tzinfo=UTC)),
    ],
)
def test_raw_dates_use_campus_timezone_before_separate_clock(day, expected):
    client, _ = client_for([item(**{"Starts": day, "Ends": day})])
    with client:
        notices = scrape(SPEC, now=NOW, client=client)
    assert notices[0].start_time == expected


def test_unparseable_raw_date_stays_in_review():
    client, _ = client_for([item(**{"Starts": "2026-11-14T00:00:00"})])
    with client:
        notices = scrape(SPEC, now=NOW, client=client)
    assert notices[0].start_time is None
    assert notices[0].issues


def test_sharepoint_double_encoded_column_names():
    encoded = item()
    encoded = {key.replace("_", "_x005f_"): value for key, value in encoded.items()}
    client, _ = client_for([encoded])
    with client:
        notices = scrape(SPEC, now=NOW, client=client)
    assert notices[0].start_time == datetime(2026, 11, 14, 11, tzinfo=UTC)
    assert notices[0].text == "The east elevator is out of service."


def test_sparse_sharepoint_fields_become_unresolved_not_a_failed_download():
    sparse = item()
    for title in ("Ends", "End Time", "Building", "DOC ID#"):
        internal = next(field["InternalName"] for field in FIELDS if field["Title"] == title)
        sparse.pop(internal)
    client, _ = client_for([sparse])
    with client:
        notices = scrape(SPEC, now=NOW, client=client)
    assert len(notices) == 1
    assert notices[0].end_time is None and notices[0].building == ""
    assert "item-1" in notices[0].id


def test_encoded_and_capitalized_pagination_link():
    link = PREFIX.replace("/web/lists", "/Web/Lists").replace("'", "%27")
    client, _ = client_for(
        [item(text="The east elevator is broken.")], next_link=link + "/Items?$skiptoken=second"
    )
    with client:
        notices = scrape(SPEC, now=NOW, client=client)
    assert len(notices) == 2


def test_live_cache_is_preferred_and_never_freshened_on_failure(tmp_path):
    fallback = export_file(tmp_path, text="The east elevator has reopened.")
    spec = {**SPEC, "fallback": {"kind": "csv", "path": str(fallback)}}
    client, _ = client_for()
    with client:
        live = load_sharepoint(spec, base=tmp_path, now=NOW, client=client)
    cache = tmp_path / "data/private/sharepoint-notices.json"
    original = cache.read_bytes()
    with unavailable() as client:
        saved = load_sharepoint(spec, base=tmp_path, now=NOW + timedelta(hours=1), client=client)
    assert saved.state.mode == "cache"
    assert saved.state.observed_at == NOW
    assert saved.notices == live.notices
    assert cache.read_bytes() == original


def test_no_cache_uses_export_only_after_live_failure(tmp_path):
    fallback = export_file(tmp_path)
    spec = {**SPEC, "fallback": {"kind": "csv", "path": str(fallback)}}
    with unavailable(503) as client:
        batch = load_sharepoint(spec, base=tmp_path, now=NOW, client=client)
    assert batch.state.mode == "spreadsheet_fallback"
    assert batch.state.observed_at == NOW - timedelta(hours=3)
    assert "HTTP 503" in batch.state.message
    assert not (tmp_path / "data/private/sharepoint-notices.json").exists()


@pytest.mark.parametrize("status", [302, 401, 403, 500])
def test_http_failure_without_any_fallback_is_an_error(tmp_path, status):
    with unavailable(status) as client, pytest.raises(SourceError):
        load_sharepoint(SPEC, base=tmp_path, now=NOW, client=client)


def test_login_html_is_not_empty_success():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                text="<html>Sign in to your account</html>",
                headers={"Content-Type": "text/html"},
            )
        )
    )
    with client, pytest.raises(SourceError, match="non-JSON"):
        scrape(SPEC, now=NOW, client=client)


def test_partial_fetch_does_not_replace_saved_cache(tmp_path):
    good, _ = client_for()
    with good:
        live = load_sharepoint(SPEC, base=tmp_path, now=NOW, client=good)
    broken, _ = client_for(next_link=PREFIX + "/items?$skiptoken=second", next_status=503)
    with broken:
        batch = load_sharepoint(SPEC, base=tmp_path, now=NOW + timedelta(hours=1), client=broken)
    assert batch.state.mode == "cache"
    assert batch.notices == live.notices


@pytest.mark.parametrize("link", ["https://elsewhere.example/steal", SITE + "/_api/other"])
def test_pagination_stays_on_the_selected_list(link):
    client, calls = client_for(next_link=link)
    with client, pytest.raises(SourceError, match="pagination URL"):
        scrape(SPEC, now=NOW, client=client)
    assert len(calls) == 2


def test_schema_validated_empty_list_and_pipeline(tmp_path, monkeypatch):
    client, _ = client_for([])
    with client:
        batch = load_sharepoint(SPEC, base=tmp_path, now=NOW, client=client)
    assert batch.notices == [] and batch.state.mode == "live"
    monkeypatch.setattr("campus_notices.pipeline.load_batch", lambda *a, **kw: batch)
    registry = tmp_path / "locations.json"
    registry.write_text("[]")
    output = tmp_path / "official_snapshot.json"
    snapshot = refresh(
        sources=[SPEC], base=tmp_path, registry_path=registry, output=output, now=NOW
    )
    assert snapshot.source_observed_at[SPEC["id"]] == NOW
    assert snapshot.counts["imported"] == 0
    assert not snapshot_status(output, NOW)["stale"]


def test_malformed_item_or_schema_never_clears_known_data():
    client, _ = client_for([{"Id": 1}])
    with client, pytest.raises(SourceError, match="no recognizable notice fields"):
        scrape(SPEC, now=NOW, client=client)
    bad = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"d": {"results": []}},
            )
        )
    )
    with bad, pytest.raises(SourceError, match="columns need mapping"):
        scrape(SPEC, now=NOW, client=bad)


def test_live_and_export_have_same_identity(tmp_path):
    csv_path = export_file(tmp_path, **{"Starts": "2026-11-14", "Start Time": "06:00"})
    client, _ = client_for()
    with client:
        live = scrape(SPEC, now=NOW, client=client)
    export = load_source(
        {"id": SPEC["id"], "kind": "csv", "path": str(csv_path)}, base=tmp_path, now=NOW
    )
    assert live[0].id == export[0].id


def test_expired_or_other_tenant_cookies_are_not_usable(tmp_path):
    state = tmp_path / "session.json"
    state.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "FedAuth",
                        "value": "dummy",
                        "domain": "elsewhere.example",
                        "expires": -1,
                    },
                    {
                        "name": "FedAuth",
                        "value": "dummy",
                        "domain": "umass.sharepoint.com",
                        "expires": NOW.timestamp() - 1,
                    },
                ]
            }
        )
    )
    with pytest.raises(AuthenticationRequired):
        read_session(state, NOW)
    state.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "FedAuth",
                        "value": "dummy",
                        "domain": ".umass.sharepoint.com",
                        "expires": NOW.timestamp() + 3600,
                    },
                    {
                        "name": "other",
                        "value": "dummy",
                        "domain": "login.microsoftonline.com",
                        "expires": -1,
                    },
                ]
            }
        )
    )
    session, _ = read_session(state, NOW)
    assert [c["name"] for c in session["cookies"]] == ["FedAuth"]


def test_fallback_provenance_and_closure_expiry(tmp_path, monkeypatch):
    csv_path = export_file(tmp_path)
    with unavailable() as client:
        batch = load_sharepoint(
            {**SPEC, "fallback": {"kind": "csv", "path": str(csv_path)}},
            base=tmp_path,
            now=NOW,
            client=client,
        )
    monkeypatch.setattr("campus_notices.pipeline.load_batch", lambda *a, **kw: batch)
    registry = Path(__file__).resolve().parents[1] / "examples/role3/locations.json"
    output = tmp_path / "official_snapshot.json"
    snapshot = refresh(
        sources=[SPEC], base=tmp_path, registry_path=registry, output=output, now=NOW, demo=True
    )
    status = snapshot_status(output, NOW)
    assert status["stale"]
    assert status["last_attempt"]["status"] == "fallback"
    assert status["source_status"][SPEC["id"]]["mode"] == "spreadsheet_fallback"
    assert snapshot.closures[0].last_confirmed == NOW - timedelta(hours=3)
    assert snapshot_status(output, NOW + timedelta(hours=4))["active_count"] == 0


def test_swagger_example_is_executable():
    with TestClient(create_app(engine=RoutingEngine(make_demo_graph()))) as client:
        schema = client.get("/openapi.json").json()
        example = schema["components"]["schemas"]["RouteRequest"]["examples"][0]
        result = client.post("/route", json=example)
        assert result.status_code == 200
        assert not result.json()["properties"]["uses_stairs"]


def test_older_fallback_cannot_replace_fresher_published_closures(tmp_path, monkeypatch):
    client, _ = client_for()
    with client:
        batch = load_sharepoint(SPEC, base=tmp_path, now=NOW, client=client)
    monkeypatch.setattr("campus_notices.pipeline.load_batch", lambda *a, **kw: batch)
    registry = Path(__file__).resolve().parents[1] / "examples/role3/locations.json"
    output = tmp_path / "official_snapshot.json"
    before = refresh(
        sources=[SPEC], base=tmp_path, registry_path=registry, output=output, now=NOW, demo=True
    )
    # Model a lost source cache followed by an older export with changed content.
    older = batch.notices[0].model_copy(
        update={
            "text": "The east elevator has reopened.",
            "observed_at": NOW - timedelta(hours=3),
        }
    )
    batch = batch.model_copy(
        update={
            "notices": [older],
            "state": batch.state.model_copy(
                update={
                    "mode": "spreadsheet_fallback",
                    "observed_at": older.observed_at,
                }
            ),
        }
    )
    after = refresh(
        sources=[SPEC],
        base=tmp_path,
        registry_path=registry,
        output=output,
        now=NOW + timedelta(minutes=30),
        demo=True,
    )
    assert before.closures and after.closures == before.closures
    assert after.counts["older_ignored"] == 1
    assert after.source_observed_at[SPEC["id"]] == NOW
    assert snapshot_status(output, NOW)["stale"]
