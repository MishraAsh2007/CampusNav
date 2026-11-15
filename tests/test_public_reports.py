import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from campus_notices.models import Extraction, Impact
from campus_notices.public_sources import (
    NotConfigured,
    PublicPost,
    download,
    fetch_posts,
    read_facebook,
    read_feed,
    read_html,
    read_pvta,
    read_reddit,
)
from campus_notices.reports import refresh_reports, reports_status
from campus_notices.sources import SourceError

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
SPEC = {"id": "public", "kind": "rss", "authority": "community"}


def sample(ident="1", *, published=NOW, text="The east elevator is broken."):
    return PublicPost(
        native_id=ident,
        url=f"https://example.org/{ident}",
        title="Campus report",
        text=text,
        published_at=published,
    )


def refresh(tmp_path, items=None, **kwargs):
    registry = tmp_path / "locations.json"
    registry.write_text("[]")
    options = {
        "sources": [SPEC],
        "output": tmp_path / "reports.json",
        "registry_path": registry,
        "now": NOW,
        "fetcher": lambda spec, **kw: [sample()] if items is None else items,
    }
    return refresh_reports(**(options | kwargs))


def test_rss_dates_and_contact_redaction():
    posts = read_feed(
        b"""<rss><channel><item><title>Elevator broken</title>
      <link>https://example.org/report</link><description>Ask u/example or x@example.edu
      or 413-555-0123.</description><pubDate>Sat, 14 Nov 2026 07:00:00 -0500</pubDate>
      </item></channel></rss>""",
        "https://example.org/feed",
    )
    assert posts[0].published_at == NOW
    assert "u/example" not in posts[0].text and "@example.edu" not in posts[0].text
    assert "555-0123" not in posts[0].text


def test_atom_does_not_use_updated_as_publication():
    posts = read_feed(
        b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>1</id><title>Ramp closed</title><link href="https://example.org/1"/>
      <summary>Ramp blocked</summary><updated>2026-11-14T12:00:00Z</updated>
      </entry></feed>""",
        "https://example.org/feed",
    )
    assert posts[0].published_at is None


@pytest.mark.parametrize(
    "data", [b"<html>Login</html>", b"<rss/>", b"not xml", b"<!DOCTYPE rss><rss><channel/></rss>"]
)
def test_invalid_feed_is_not_an_empty_success(data):
    with pytest.raises(SourceError):
        read_feed(data, "https://example.org/feed")


def test_html_requires_structured_reports_or_explicit_empty_marker():
    spec = {"url": "https://example.org/", "item_selector": "article"}
    with pytest.raises(SourceError):
        read_html(b"<main>Something changed</main>", spec)
    with pytest.raises(SourceError):
        read_html(b'<input type="password">', spec)
    assert read_html(b'<p class="empty">No reports</p>', spec | {"empty_selector": ".empty"}) == []
    posts = read_html(
        b"""<article><h2>Elevator out</h2><a href="/1">Details</a>
        <p class="description">Elevator broken</p><time datetime="2026-11-14T12:00:00Z"/>
        </article>""",
        spec,
    )
    assert posts[0].url == "https://example.org/1" and posts[0].published_at == NOW


def test_pvta_filters_route_badges_not_incidental_numbers():
    data = b"""<div>33</div><h3>Library stop closed</h3><p>Effect: No Service</p>
      <p>The bus stop is closed.</p><div>G1</div><h3>Other route</h3>
      <p>Effect: Detour</p><p>Closed for 33 minutes on 11/14.</p>
      <div>34</div><h3>Stadium detour</h3><p>Effect: Detour</p><p>Bus detour.</p>"""
    posts = read_pvta(data, {"33", "34"})
    assert [p.title for p in posts] == ["Library stop closed", "Stadium detour"]
    assert all(p.published_at is None for p in posts)
    assert len({p.native_id for p in posts}) == 2
    assert read_pvta(b"<p>No active alerts</p>", {"33"}) == []
    with pytest.raises(SourceError):
        read_pvta(b"<p>Service unavailable</p>", {"33"})


def test_reddit_needs_config_and_uses_header_auth(monkeypatch):
    monkeypatch.delenv("REDDIT_ACCESS_TOKEN", raising=False)
    with pytest.raises(NotConfigured):
        read_reddit(None, {})
    monkeypatch.setenv("REDDIT_ACCESS_TOKEN", "test-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "test-app")
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert "test-secret" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "data": {
                                "name": "t3_1",
                                "permalink": "/r/umass/comments/1/test/",
                                "body": "The elevator is broken",
                                "created_utc": NOW.timestamp(),
                            }
                        },
                        {"data": {"body": "[deleted]"}},
                        {"data": {"body": "[removed]"}},
                    ]
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        posts = read_reddit(client, {})
    assert len(calls) == 2 and len(posts) == 2
    assert posts[0].published_at == NOW


def test_reddit_public_feed_preserves_review_identity_when_switching_to_api(tmp_path, monkeypatch):
    monkeypatch.delenv("REDDIT_ACCESS_TOKEN", raising=False)
    spec = SPEC | {"kind": "reddit", "public_feed": True, "include_comments": False}
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>t3_1</id><title>Elevator is broken</title>
      <link href="https://www.reddit.com/r/umass/comments/1/test?ref=rss"/>
      <summary>Elevator unavailable.</summary><updated>2026-11-14T12:00:00Z</updated>
      </entry></feed>"""

    def handle(request):
        if request.url.host == "www.reddit.com":
            assert request.url.path == "/r/umass/new/.rss"
            assert "Authorization" not in request.headers
            return httpx.Response(200, content=feed)
        assert request.url.host == "oauth.reddit.com"
        return httpx.Response(
            200,
            json={
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "data": {
                                "name": "t3_1",
                                "permalink": "/r/umass/comments/1/test/",
                                "title": "Elevator is broken",
                                "created_utc": NOW.timestamp(),
                            }
                        }
                    ]
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        options = {"client": client, "sources": [spec], "fetcher": fetch_posts}
        first = refresh(tmp_path, **options).reports[0]
        assert first.published_at is None and not first.routing_eligible
        monkeypatch.setenv("REDDIT_ACCESS_TOKEN", "test-secret")
        monkeypatch.setenv("REDDIT_USER_AGENT", "test-app")
        later = refresh(tmp_path, **options, now=NOW + timedelta(hours=1)).reports[0]
        assert later.id == first.id and later.expires_at == first.expires_at
        assert later.published_at == NOW and later.review_status == "needs_review"


@pytest.mark.parametrize("status", [403, 429])
def test_reddit_api_denial_does_not_switch_to_public_feed(monkeypatch, status):
    monkeypatch.setenv("REDDIT_ACCESS_TOKEN", "test-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "test-app")

    def handle(request):
        assert request.url.host == "oauth.reddit.com"
        return httpx.Response(status)

    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as client,
        pytest.raises(SourceError, match=str(status)),
    ):
        read_reddit(client, {"public_feed": True})


def test_facebook_requires_page_config_and_keeps_token_off_url(monkeypatch):
    monkeypatch.setenv("FACEBOOK_PAGE_ACCESS_TOKEN", "test-secret")
    with pytest.raises(NotConfigured):
        read_facebook(None, {})

    def handle(request):
        assert request.url.host == "graph.facebook.com"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert "test-secret" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "123_1",
                        "message": "Ramp blocked",
                        "permalink_url": "https://www.facebook.com/123/posts/1",
                        "created_time": "2026-11-14T12:00:00+0000",
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        posts = read_facebook(client, {"page_id": "123"})
    assert posts[0].published_at == NOW


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_network_failures_are_errors_without_response_secrets(status):
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="secret response")
            )
        ) as client,
        pytest.raises(SourceError) as error,
    ):
        download(client, "https://example.org/feed")
    assert "secret response" not in str(error.value)


def test_reports_never_become_closures_and_observations_do_not_extend_expiry(tmp_path):
    first = refresh(tmp_path, [sample(published=None)])
    report = first.reports[0]
    assert not report.routing_eligible and report.review_status == "needs_review"
    assert report.published_at is None and report.parser == "rules"
    assert report.extraction.impacts[0].start_time is None
    later = refresh(tmp_path, [sample(published=None)], now=NOW + timedelta(hours=23))
    assert later.reports[0].first_seen_at == NOW
    assert later.reports[0].expires_at == report.expires_at
    assert later.reports[0].last_seen_at == NOW + timedelta(hours=23)
    expired = refresh(tmp_path, [sample(published=None)], now=NOW + timedelta(hours=25))
    assert expired.reports == [] and expired.observed
    again = refresh(tmp_path, [sample(published=None)], now=NOW + timedelta(hours=26))
    assert again.reports == []


def test_expired_future_and_unrelated_claims_are_not_displayed(tmp_path):
    result = refresh(
        tmp_path,
        [
            sample("1", published=NOW - timedelta(days=2)),
            sample("2", published=NOW + timedelta(days=1)),
            sample("3", text="Lunch was good."),
        ],
    )
    assert not result.reports


def test_source_failure_keeps_cache_timestamps_and_other_sources_work(tmp_path):
    first = refresh(tmp_path)

    def fetch(spec, **kw):
        if spec["id"] == "public":
            raise SourceError("Source access denied (HTTP 401)")
        return [sample("2")]

    result = refresh(
        tmp_path,
        sources=[SPEC, SPEC | {"id": "other"}],
        fetcher=fetch,
        now=NOW + timedelta(hours=1),
    )
    assert result.sources["public"].state == "cached"
    assert result.sources["other"].state == "live"
    assert next(r for r in result.reports if r.source_id == "public") == first.reports[0]
    assert reports_status(tmp_path / "reports.json", NOW + timedelta(hours=1))["stale"]
    expired = refresh(tmp_path, fetcher=fetch, now=NOW + timedelta(hours=25))
    assert expired.reports == []


def test_successful_empty_feed_drops_removed_reports(tmp_path):
    refresh(tmp_path)
    result = refresh(tmp_path, [])
    assert result.reports == [] and result.sources["public"].state == "live"


def test_optional_gemini_only_runs_after_rules_abstain_and_failure_keeps_review(tmp_path):
    class Parser:
        calls = 0

        def extract(self, *args):
            self.calls += 1
            raise RuntimeError("secret")

    parser = Parser()
    result = refresh(
        tmp_path, [sample("1"), sample("2", text="Elevator feels odd.")], extractor=parser
    )
    assert parser.calls == 1 and len(result.reports) == 2
    assert "secret" not in result.model_dump_json()
    assert result.reports[1].parser == "unresolved"


def test_unverified_gemini_location_is_rejected(tmp_path):
    class Parser:
        def extract(self, *args):
            return Extraction(
                impacts=[
                    Impact(
                        type="elevator",
                        status="closed",
                        evidence="Elevator feels odd.",
                        location_id="invented",
                    )
                ]
            )

    result = refresh(tmp_path, [sample(text="Elevator feels odd.")], extractor=Parser())
    assert result.reports[0].extraction is None
    assert result.reports[0].routing_eligible is False


def test_cached_api_filters_expired_reports_and_reports_unavailable(tmp_path):
    from fastapi.testclient import TestClient

    from campus_routing.api import create_app
    from campus_routing.engine import RoutingEngine
    from scripts.make_demo import make_demo_graph

    clock = datetime.now(UTC)
    path = tmp_path / "reports.json"
    app = create_app(engine=RoutingEngine(make_demo_graph()), reports_path=path)
    with TestClient(app) as client:
        assert client.get("/external-reports").status_code == 503
        refresh(tmp_path, [sample(published=clock)], now=clock)
        response = client.get("/external-reports", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.json()[0]["routing_eligible"] is False
        assert "X-Reports-Stale" in response.headers["access-control-expose-headers"]
        saved = json.loads(path.read_text())
        saved["reports"][0]["expires_at"] = (clock - timedelta(seconds=1)).isoformat()
        path.write_text(json.dumps(saved))
        assert client.get("/external-reports").json() == []
        assert client.get("/external-reports/status").json()["report_count"] == 0
    assert not (tmp_path / "official_snapshot.json").exists()
