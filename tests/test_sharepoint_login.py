import json
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import pytest

from campus_notices.sharepoint import (
    LIST_URL,
    REQUIRED,
    BrowserSessionTransport,
    SharePointAccessDenied,
    _collection,
    endpoints,
    scoped_storage_state,
)
from campus_notices.sources import SourceError
from scripts.login_notices import probe_items, verification_loop, verify_and_save

NOW = datetime(2026, 11, 14, tzinfo=UTC)
PREFIX = endpoints({})[1]


def test_login_probe_does_not_follow_next_link_for_single_sample():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"d": {"results": [{"Id": 1}], "__next": PREFIX + "/items?$skiptoken=second"}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe_items(client, PREFIX) == 1
    assert len(calls) == 1


def cookie(name, domain, path="/"):
    return {
        "name": name,
        "value": "test-only",
        "domain": domain,
        "path": path,
        "expires": -1,
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    }


def state():
    return {
        "cookies": [
            cookie("FedAuth", ".umass.sharepoint.com", "/sites/impactnotices/"),
            cookie("FedAuth1", ".umass.sharepoint.com", "/sites/impactnotices/"),
            cookie("rtFa", ".sharepoint.com"),
            cookie("other-tenant", "other.sharepoint.com"),
            cookie("login", ".login.microsoftonline.com"),
        ],
        "origins": [
            {
                "origin": "https://login.microsoftonline.com",
                "localStorage": [{"name": "unrelated", "value": "test-only"}],
            }
        ],
    }


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.headers = {"content-type": "application/json", "set-cookie": "never-copy-this"}
        self.payload = payload
        self.disposed = False

    def body(self):
        return json.dumps(self.payload).encode()

    def dispose(self):
        self.disposed = True


class FakeRequests:
    def __init__(self, status=200):
        self.status = status
        self.calls = []
        self.responses = []
        self.disposed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if urlparse(url).path.endswith("/fields"):
            rows = [
                {"Title": title, "InternalName": f"field{i}"} for i, title in enumerate(REQUIRED)
            ]
        else:
            rows = [
                {
                    "Id": 1,
                    "FieldValuesAsText": dict(
                        zip(
                            [f"field{i}" for i in range(len(REQUIRED))],
                            [
                                "1",
                                "Demo Center",
                                "11/14/2026",
                                "6:00 AM",
                                "11/14/2026",
                                "10:00 AM",
                                "The east elevator is out of service.",
                            ],
                            strict=True,
                        )
                    ),
                }
            ]
        response = FakeResponse(self.status, {"d": {"results": rows}, "secret": "never-log-me"})
        self.responses.append(response)
        return response

    def dispose(self):
        self.disposed = True


def environment(*, initial_status=200, restored_status=200):
    browser_requests = FakeRequests(initial_status)
    saved_requests = FakeRequests(restored_status)
    created = []

    def new_context(**kwargs):
        created.append(kwargs)
        return saved_requests

    page = SimpleNamespace(
        url=LIST_URL, evaluate=lambda expression: "Test Chrome user agent", is_closed=lambda: False
    )
    context = SimpleNamespace(request=browser_requests, storage_state=state, pages=[page])
    playwright = SimpleNamespace(request=SimpleNamespace(new_context=new_context))
    return context, page, playwright, saved_requests, created


def test_parent_and_site_path_cookies_survive_without_identity_provider_secrets():
    saved = scoped_storage_state(state(), NOW)
    assert [c["name"] for c in saved["cookies"]] == ["FedAuth", "FedAuth1", "rtFa"]
    assert saved["cookies"][0]["path"] == "/sites/impactnotices/"
    assert saved["cookies"][0]["sameSite"] == "None"
    assert saved["cookies"][2]["domain"] == ".sharepoint.com"
    assert saved["origins"] == []


def test_browser_request_preserves_context_and_disables_redirects():
    requests = FakeRequests()
    diagnostics = []
    with httpx.Client(
        transport=BrowserSessionTransport(
            requests,
            prefix=PREFIX,
            diagnostics=diagnostics,
        )
    ) as client:
        response = client.get(PREFIX + "/fields", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert requests.calls[0][1]["max_redirects"] == 0
    assert requests.calls[0][1]["headers"] == {"Accept": "application/json"}
    assert diagnostics == [{"stage": "fields", "http_status": 200}]
    assert requests.responses[0].disposed


def test_scraper_can_use_fresh_saved_context_for_every_page_and_disposes_them():
    contexts = []

    def factory():
        context = FakeRequests()
        contexts.append(context)
        return context

    with httpx.Client(
        transport=BrowserSessionTransport(prefix=PREFIX, context_factory=factory)
    ) as client:
        assert client.get(PREFIX + "/fields").status_code == 200
        assert client.get(PREFIX + "/items").status_code == 200
        with pytest.raises(SourceError):
            client.get("https://other.sharepoint.com/fields")
    assert len(contexts) == 2
    assert all(len(c.calls) == 1 and c.disposed for c in contexts)
    assert all(c.responses[0].disposed for c in contexts)


@pytest.mark.parametrize(
    "method,url", [("POST", PREFIX + "/items"), ("GET", "https://other.sharepoint.com/fields")]
)
def test_browser_transport_cannot_write_or_send_parent_cookie_to_another_tenant(method, url):
    requests = FakeRequests()
    with httpx.Client(transport=BrowserSessionTransport(requests, prefix=PREFIX)) as client:
        with pytest.raises(SourceError):
            client.request(method, url)
    assert not requests.calls


def test_403_reports_access_denial_instead_of_reauthentication():
    requests, diagnostics = FakeRequests(403), []
    with httpx.Client(
        transport=BrowserSessionTransport(
            requests,
            prefix=PREFIX,
            diagnostics=diagnostics,
        )
    ) as client:
        with pytest.raises(SharePointAccessDenied, match="HTTP 403") as exc:
            _collection(client, PREFIX + "/fields", PREFIX)
    assert "sign-in again" not in str(exc.value)
    assert "never-log-me" not in str(exc.value)
    assert diagnostics == [{"stage": "fields", "http_status": 403}]


def test_verification_checks_live_browser_and_restored_session_before_saving(tmp_path):
    context, page, playwright, restored, created = environment()
    destination = tmp_path / "session.json"
    diagnostics = []
    assert verify_and_save(context, page, playwright, destination, diagnostics) == 1
    saved = json.loads(destination.read_text())
    assert saved["version"] == 2
    assert saved["user_agent"] == "Test Chrome user agent"
    assert len(created) == 1 and len(created[0]["storage_state"]["cookies"]) == 3
    assert created[0]["user_agent"] == saved["user_agent"]
    assert restored.disposed
    assert len(context.request.calls) == 2 and len(restored.calls) == 2
    assert all(item["http_status"] == 200 for item in diagnostics)


def test_failed_saved_session_check_preserves_previous_session(tmp_path):
    context, page, playwright, restored, _ = environment(restored_status=403)
    destination = tmp_path / "session.json"
    destination.write_text("previous-session")
    with pytest.raises(SharePointAccessDenied):
        verify_and_save(context, page, playwright, destination, [])
    assert destination.read_text() == "previous-session"
    assert restored.disposed


def test_saved_session_cannot_pass_with_only_metadata_access(tmp_path):
    context, page, playwright, restored, _ = environment()
    original_get = restored.get

    def fields_only(url, **kwargs):
        if urlparse(url).path.endswith("/items"):
            return FakeResponse(401, {"error": "test-only"})
        return original_get(url, **kwargs)

    restored.get = fields_only
    destination = tmp_path / "session.json"
    destination.write_text("previous-session")
    with pytest.raises(SourceError, match="HTTP 401"):
        verify_and_save(context, page, playwright, destination, [])
    assert destination.read_text() == "previous-session"
    assert restored.disposed


def test_unfinished_login_does_not_export_session(tmp_path):
    context, page, playwright, _, created = environment(initial_status=401)
    page.url = "https://login.microsoftonline.com/"
    destination = tmp_path / "session.json"
    with pytest.raises(SourceError, match="HTTP 401"):
        verify_and_save(context, page, playwright, destination, [])
    assert not created and len(context.request.calls) == 1 and not destination.exists()


@pytest.mark.parametrize(
    "cached_url",
    [
        "https://login.microsoftonline.com/stale",
        "https://umass.sharepoint.com/sites/impactnotices",
        "https://umass.sharepoint.com/sites/ImpactNotices/Lists/Service%20Interruption%20Notices/",
    ],
)
def test_cached_url_cannot_block_an_authenticated_list_request(tmp_path, cached_url):
    context, page, playwright, _, _ = environment()
    page.url = cached_url
    destination = tmp_path / "session.json"
    assert verify_and_save(context, page, playwright, destination, []) == 1
    assert destination.exists() and len(context.request.calls) == 2


def test_sign_in_completed_in_new_tab_after_original_closed(tmp_path):
    context, page, playwright, _, _ = environment()
    page.is_closed = lambda: True
    page.evaluate = lambda expression: pytest.fail("Should not read the closed login tab")
    notice_tab = SimpleNamespace(
        is_closed=lambda: False, evaluate=lambda expression: "New tab user agent"
    )
    context.pages = [page, notice_tab]
    destination = tmp_path / "session.json"
    assert verify_and_save(context, page, playwright, destination, []) == 1
    assert json.loads(destination.read_text())["user_agent"] == "New tab user agent"


def test_reload_retries_with_existing_browser_without_another_login(tmp_path, monkeypatch):
    context, page, playwright, _, _ = environment()
    calls = []

    def corrected_verifier(*args):
        calls.append(args)
        return 4

    monkeypatch.setattr(
        "scripts.login_notices.importlib.reload",
        lambda module: SimpleNamespace(verify_and_save=corrected_verifier),
    )
    success = verification_loop(
        context,
        page,
        playwright,
        tmp_path / "session.json",
        diagnostic_path=tmp_path / "diagnostic.json",
        prompt=lambda message: "r",
    )
    assert success and calls[0][0] is context and calls[0][1] is page


def test_verification_retry_uses_same_open_browser_and_sanitized_diagnostics(tmp_path, monkeypatch):
    context, page, playwright, _, _ = environment(initial_status=403)
    answers = iter(["", "q"])
    diagnostic = tmp_path / "diagnostic.json"
    success = verification_loop(
        context,
        page,
        playwright,
        tmp_path / "session.json",
        diagnostic_path=diagnostic,
        prompt=lambda message: next(answers),
    )
    assert not success
    saved = json.loads(diagnostic.read_text())
    assert saved["error_type"] == "SharePointAccessDenied"
    assert saved["requests"] == [{"stage": "fields", "http_status": 403}]
    assert "test-only" not in diagnostic.read_text()
    assert "never-log-me" not in diagnostic.read_text()
