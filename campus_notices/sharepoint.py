"""Read the authenticated UMass SharePoint list, with explicit offline fallback.

Only GET requests are made. No password, contact columns, or browser state is logged
or put in the notice cache. Authentication is bootstrapped separately by the user.
"""

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlencode, urljoin, urlparse
from uuid import UUID

import httpx

from .cache import atomic_json
from .models import SourceBatch, SourceState
from .sources import LOCAL_ZONE, MAX_BYTES, SourceError, _table_notices, load_source

SITE = "https://umass.sharepoint.com/sites/impactnotices"
LIST_ID = "73963677-5e24-4eac-96a3-95a82dc03118"
VIEW_ID = "5521f93e-d5c5-4803-9c36-9ed0f441c0e9"
LIST_URL = (
    SITE + "/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx?viewid=" + VIEW_ID
)
REQUIRED = ("DOC ID#", "Building", "Starts", "Start Time", "Ends", "End Time", "Desc")
OPTIONAL = (
    "Building Safety Security",
    "HVAC",
    "Power Electrical",
    "Water Plumbing",
    "Other Service",
)


class AuthenticationRequired(SourceError):
    pass


class SharePointAccessDenied(SourceError):
    pass


def resolve_path(value, base):
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def endpoints(spec):
    site = spec.get("site_url", SITE).rstrip("/")
    # This connector is deliberately scoped to the tenant/site the user supplied.
    if site != SITE:
        raise SourceError("The UMass scraper expects the impactnotices SharePoint site")
    try:
        list_id = str(UUID(spec.get("list_id", LIST_ID)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SourceError("Invalid SharePoint list GUID") from exc
    return site, f"{site}/_api/web/lists(guid'{list_id}')"


def scoped_storage_state(state: dict, now: datetime) -> dict:
    """Keep cookies applicable to this tenant, including parent-domain/site-path cookies.

    Let Playwright preserve the original cookie attributes instead of rebuilding them
    with another HTTP library. Only the selected list can be requested by the adapter.
    """
    try:
        entries = state["cookies"]
        if not isinstance(entries, list):
            raise ValueError
    except (ValueError, KeyError, TypeError) as exc:
        raise AuthenticationRequired(
            "Malformed saved session. Run .\\login-notices.cmd again."
        ) from exc
    cookies = []
    host = urlparse(SITE).hostname
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("domain"), str):
            raise AuthenticationRequired("Malformed saved session. Run .\\login-notices.cmd again.")
        domain = item.get("domain", "")
        cookie_host = domain.lstrip(".").lower()
        # SharePoint may scope rtFa to the parent domain. Sign-in-provider cookies
        # and cookies for other tenants are never saved or sent by this connector.
        if cookie_host not in (host, "sharepoint.com"):
            continue
        expiry = item.get("expires", -1)
        if (
            not isinstance(expiry, (int, float))
            or not math.isfinite(expiry)
            or not all(isinstance(item.get(key), str) for key in ("name", "value"))
            or not isinstance(item.get("path", "/"), str)
        ):
            raise AuthenticationRequired("Malformed saved session. Run .\\login-notices.cmd again.")
        if expiry != -1 and expiry <= now.timestamp():
            continue
        cookies.append(
            {
                key: item[key]
                for key in (
                    "name",
                    "value",
                    "domain",
                    "path",
                    "expires",
                    "httpOnly",
                    "secure",
                    "sameSite",
                    "partitionKey",
                )
                if key in item
            }
        )
        cookies[-1].setdefault("path", "/")
    if not cookies:
        raise AuthenticationRequired(
            "UMass session is missing or expired. Run .\\login-notices.cmd."
        )
    return {"cookies": cookies, "origins": []}


def read_session(path: Path, now: datetime):
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthenticationRequired("Run .\\login-notices.cmd to connect UMass first.") from exc
    state = scoped_storage_state(saved, now)
    user_agent = saved.get("user_agent")
    if user_agent is not None and (
        not isinstance(user_agent, str)
        or len(user_agent) > 1000
        or "\n" in user_agent
        or "\r" in user_agent
    ):
        raise SourceError("Invalid saved browser metadata. Run .\\login-notices.cmd again.")
    return state, user_agent


class BrowserSessionTransport(httpx.BaseTransport):
    """Adapter for Playwright's own request context; no manual cookie copying."""

    def __init__(self, request_context, *, prefix, diagnostics=None):
        self.request_context = request_context
        self.prefix = prefix
        self.diagnostics = diagnostics if diagnostics is not None else []

    def handle_request(self, request):
        url = str(request.url)
        _safe_endpoint(url, self.prefix)
        if request.method != "GET":
            raise SourceError("The notice scraper only permits read-only GET requests")
        try:
            result = self.request_context.get(
                url,
                headers={"Accept": request.headers.get("accept", "application/json;odata=verbose")},
                max_redirects=0,
                timeout=30000,
                fail_on_status_code=False,
            )
        except Exception as exc:
            self.diagnostics.append(
                {"stage": urlparse(url).path.rsplit("/", 1)[-1], "error_type": type(exc).__name__}
            )
            raise SourceError(
                f"The SharePoint request could not complete ({type(exc).__name__}). "
                "Check the connection; this does not establish a sign-in failure."
            ) from None
        try:
            self.diagnostics.append(
                {
                    "stage": urlparse(url).path.rsplit("/", 1)[-1],
                    "http_status": result.status,
                }
            )
            body = result.body()
            if len(body) > MAX_BYTES:
                raise SourceError("SharePoint response exceeds 15 MB")
            # Playwright's body is already decompressed. Copy only headers used by
            # the scraper, never Set-Cookie or other authentication response headers.
            headers = {"Content-Type": result.headers.get("content-type", "")}
            return httpx.Response(result.status, content=body, headers=headers, request=request)
        finally:
            result.dispose()


def _safe_endpoint(url, prefix):
    parsed = urlparse(url)
    base = urlparse(prefix)
    path = unquote(parsed.path).casefold()
    base_path = unquote(base.path).casefold()
    if (
        parsed.scheme != "https"
        or parsed.netloc != base.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
        or path not in (base_path + "/fields", base_path + "/items")
    ):
        raise SourceError("Unexpected SharePoint pagination URL; no credentials were forwarded")


def _collection(client, url, prefix):
    rows, visited, byte_count = [], set(), 0
    while url:
        _safe_endpoint(url, prefix)
        if url in visited or len(visited) >= 100:
            raise SourceError("SharePoint pagination was incomplete; previous data retained")
        visited.add(url)
        try:
            with client.stream(
                "GET",
                url,
                headers={"Accept": "application/json;odata=verbose"},
                follow_redirects=False,
            ) as response:
                stage = urlparse(url).path.rsplit("/", 1)[-1]
                if response.is_redirect:
                    raise AuthenticationRequired(
                        f"SharePoint redirected the {stage} request (HTTP {response.status_code}). "
                        "The list API did not accept this session."
                    )
                if response.status_code == 401:
                    raise AuthenticationRequired(
                        f"SharePoint rejected the {stage} request (HTTP 401). "
                        "The saved session is not authenticated for the list API."
                    )
                if response.status_code == 403:
                    raise SharePointAccessDenied(
                        f"SharePoint denied the {stage} request (HTTP 403). "
                        "List API permission or access policy may differ from the visible page; "
                        "repeated sign-ins may not help."
                    )
                if response.status_code != 200:
                    raise SourceError(f"SharePoint returned HTTP {response.status_code}")
                if "json" not in response.headers.get("content-type", "").lower():
                    raise SourceError(
                        f"SharePoint returned non-JSON data for {stage} (HTTP 200). "
                        "This may be a sign-in or service-error page."
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    byte_count += len(chunk)
                    if byte_count > MAX_BYTES:
                        raise SourceError("SharePoint response exceeds 15 MB")
                    data.extend(chunk)
            payload = json.loads(data)
        except httpx.HTTPError as exc:
            # Transport exceptions can contain sensitive request headers; never print them.
            raise SourceError(f"SharePoint connection failed ({type(exc).__name__})") from None
        except (ValueError, TypeError) as exc:
            if isinstance(exc, SourceError):
                raise
            raise SourceError("Invalid SharePoint JSON response") from None
        if not isinstance(payload, dict):
            raise SourceError("SharePoint did not return a list response")
        content = payload.get("d", payload)
        if not isinstance(content, dict):
            raise SourceError("Invalid SharePoint collection")
        page = content.get("results", content.get("value"))
        if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
            raise SourceError("SharePoint did not return a complete collection page")
        rows.extend(page)
        if len(rows) > 50000:
            raise SourceError("SharePoint row limit exceeded; previous data retained")
        next_url = (
            content.get("__next") or content.get("odata.nextLink") or content.get("@odata.nextLink")
        )
        if next_url is not None and not isinstance(next_url, str):
            raise SourceError("Invalid SharePoint pagination link")
        url = urljoin(url, next_url) if next_url else None
    return rows


def _rendered_field(values, internal, *, required):
    # FieldValuesAsText can encode each underscore a second time. Microsoft tracks
    # this behavior at https://github.com/SharePoint/sp-dev-docs/issues/1141.
    encoded = internal.replace("_", "_x005f_")
    candidates = {internal, encoded, "OData_" + internal, "OData_" + encoded}
    matches = [values[key] for key in candidates if key in values]
    if not matches:
        if required:
            raise SourceError("SharePoint item is missing required fields")
        return None
    if any(value != matches[0] for value in matches):
        raise SourceError("SharePoint item has conflicting field aliases")
    return matches[0]


def scrape(spec, *, now: datetime, client) -> list:
    """Fetch all list items, then let the pipeline filter expired/future notices.

    Read selected columns directly: this tenant's FieldValuesAsText expansion
    returns system fields only. Date columns are stored as UTC instants at local
    midnight; recover the campus-local date before combining the separate clock.
    """
    site, prefix = endpoints(spec)
    fields = _collection(client, prefix + "/fields?$select=Title,InternalName", prefix)
    names = {}
    for field in fields:
        title, internal = field.get("Title"), field.get("InternalName")
        if title in (*REQUIRED, *OPTIONAL):
            if not isinstance(internal, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z_0-9]*", internal
            ):
                raise SourceError("Invalid SharePoint field metadata")
            if title in names and names[title] != internal:
                raise SourceError("Ambiguous SharePoint field title")
            names[title] = internal
    if not set(REQUIRED).issubset(names):
        missing = ", ".join(sorted(set(REQUIRED) - names.keys()))
        raise SourceError(f"SharePoint columns need mapping: {missing}")
    query = urlencode(
        {
            "$select": ",".join(["Id", *names.values()]),
            "$orderby": "Id",
            "$top": "500",
        }
    )
    items = _collection(client, prefix + "/items?" + query, prefix)
    headers, rows, seen_ids = list(names), [], set()
    for item in items:
        item_id = item.get("Id", item.get("ID"))
        if type(item_id) is not int or item_id in seen_ids:
            raise SourceError("Invalid or repeated SharePoint item; refusing partial data")
        seen_ids.add(item_id)
        # Blank fields remain unresolved, rather than discarding the entire list.
        row = [
            _normalize_field(h, _rendered_field(item, names[h], required=False)) for h in headers
        ]
        if not any(value for value in row):
            raise SourceError("SharePoint item has no recognizable notice fields")
        if not row[headers.index("DOC ID#")]:
            row[headers.index("DOC ID#")] = f"item-{item_id}"
        rows.append(row)
    # An authenticated, schema-validated empty list is legitimate. HTML/login/errors
    # and partial pages can never reach this branch as an empty success.
    return _table_notices(
        [headers, *rows],
        spec["id"],
        site + "/Lists/Service%20Interruption%20Notices",
        now,
        allow_empty=True,
    )


def _normalize_field(title, value):
    if value is None:
        return None
    if title == "DOC ID#" and type(value) in (int, float):
        if not math.isfinite(value) or value != int(value):
            raise SourceError("SharePoint document ID is not an integer")
        return str(int(value))
    if not isinstance(value, str):
        raise SourceError("Unexpected SharePoint notice field type")
    if title in ("Starts", "Ends") and "T" in value:
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value  # The table parser records an unresolved date for review.
        if instant.tzinfo is not None:
            return instant.astimezone(LOCAL_ZONE).date().isoformat()
    return value


def fetch_live(spec, *, base, now, client=None):
    endpoints(spec)
    if client is not None:
        return scrape(spec, now=now, client=client)
    state_path = resolve_path(
        spec.get("storage_state", "data/private/sharepoint-session.json"), base
    )
    state, user_agent = read_session(state_path, now)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SourceError('Install scraper support with pip install -e ".[scraper]".') from None
    with sync_playwright() as playwright:
        request_context = playwright.request.new_context(storage_state=state, user_agent=user_agent)
        try:
            with httpx.Client(
                transport=BrowserSessionTransport(
                    request_context,
                    prefix=endpoints(spec)[1],
                )
            ) as session:
                return scrape(spec, now=now, client=session)
        finally:
            request_context.dispose()


def load_sharepoint(spec, *, base: Path, now: datetime, client=None) -> SourceBatch:
    """Always attempt live first; prefer last successful scrape over a spreadsheet."""
    source_id = spec["id"]
    cache_path = resolve_path(spec.get("cache", "data/private/sharepoint-notices.json"), base)
    _, prefix = endpoints(spec)
    try:
        notices = fetch_live(spec, base=base, now=now, client=client)
    except (SourceError, OSError) as exc:
        reason = (
            str(exc) if isinstance(exc, SourceError) else "SharePoint session could not be read"
        )
        try:
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            if saved.get("endpoint") != prefix:
                raise ValueError("Different list")
            batch = SourceBatch.model_validate(saved["batch"])
            if batch.source_id != source_id or batch.state.mode != "live":
                raise ValueError("Not a successful live scrape")
            if batch.state.observed_at > now + timedelta(minutes=5):
                raise ValueError("Future cache")
            if any(
                n.source_id != source_id or n.observed_at != batch.state.observed_at
                for n in batch.notices
            ):
                raise ValueError("Invalid source provenance")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            batch = None
        if batch is not None:
            batch.state = batch.state.model_copy(
                update={
                    "mode": "cache",
                    "attempted_at": now,
                    "message": reason + " Using the last successful scrape; timestamps unchanged.",
                }
            )
            return batch
        fallback = spec.get("fallback")
        if fallback:
            if fallback.get("kind") not in ("xlsx", "csv"):
                raise SourceError("SharePoint fallback must be a spreadsheet export") from None
            fallback = {**fallback, "id": source_id}
            notices = load_source(fallback, base=base, now=now)
            return SourceBatch(
                source_id=source_id,
                notices=notices,
                state=SourceState(
                    mode="spreadsheet_fallback",
                    observed_at=max(n.observed_at for n in notices),
                    attempted_at=now,
                    message=reason + " No scrape cache; using the spreadsheet fallback.",
                ),
            )
        raise SourceError(
            reason + " No saved scrape or spreadsheet fallback is available."
        ) from None
    batch = SourceBatch(
        source_id=source_id,
        notices=notices,
        state=SourceState(
            mode="live",
            observed_at=now,
            attempted_at=now,
            message="Authenticated SharePoint list fetched successfully.",
        ),
    )
    atomic_json(cache_path, {"endpoint": prefix, "batch": batch.model_dump(mode="json")})
    return batch


def load_batch(spec, *, base: Path, now: datetime):
    if spec["kind"] == "sharepoint":
        return load_sharepoint(spec, base=base, now=now)
    notices = load_source(spec, base=base, now=now)
    return SourceBatch(
        source_id=spec["id"],
        notices=notices,
        state=SourceState(
            mode="live" if spec["kind"] == "url" else "file",
            observed_at=max(n.observed_at for n in notices),
            attempted_at=now,
        ),
    )
