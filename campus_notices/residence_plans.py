"""Read authenticated UMass residence-hall floor plans from SharePoint.

The connector is intentionally read-only and stores only sanitized file metadata
plus downloaded plan files. Browser cookies and authentication state never enter
the cache.
"""

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from .cache import atomic_json
from .sharepoint import AuthenticationRequired, read_session

SITE = "https://umass.sharepoint.com/sites/SACLCommunications"
ROOT_FOLDER = (
    "/sites/SACLCommunications/Communications Resources/Assets/Design Files/"
    "Residential Life (RL)/Website/Residence Hall Floor Plans"
)


def _api_url(site: str, resource: str, path: str, suffix: str = "") -> str:
    encoded = quote("'" + path + "'", safe="")
    return f"{site}/_api/web/{resource}(@p){suffix}?@p={encoded}"


def _folder_url(site: str, path: str) -> str:
    encoded = quote(path, safe="/()")
    return f"{site}/_api/web/GetFolderByServerRelativePath(decodedurl='{encoded}')"


@dataclass
class _ResponseSnapshot:
    status: int
    content: bytes

    def json(self):
        return json.loads(self.content)

    def body(self):
        return self.content


class _FreshSharePointClient:
    """Use one short-lived request context per call.

    The saved SharePoint session intermittently returns 401 after repeated
    folder calls in one request context, while fresh contexts remain stable.
    """

    def __init__(self, playwright, state, user_agent):
        self.playwright = playwright
        self.state = state
        self.user_agent = user_agent

    def get(self, url, **kwargs):
        context = self.playwright.request.new_context(
            storage_state=self.state,
            user_agent=self.user_agent or "CampusNav residence-plan importer",
        )
        try:
            response = context.get(url, **kwargs)
            return _ResponseSnapshot(response.status, response.body())
        finally:
            context.dispose()


def _items(response):
    if response.status != 200:
        raise AuthenticationRequired(
            f"SharePoint residence-plan request failed (HTTP {response.status})"
        )
    payload = response.json()
    content = payload.get("d", payload)
    if not isinstance(content, dict):
        raise ValueError("Invalid SharePoint residence-plan response")
    rows = content.get("results", content.get("value", []))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Invalid SharePoint residence-plan collection")
    return rows


def _folder_contents(response):
    if response.status != 200:
        raise AuthenticationRequired(
            f"SharePoint residence-plan request failed (HTTP {response.status})"
        )
    payload = response.json()
    content = payload.get("d", payload)
    if not isinstance(content, dict):
        raise ValueError("Invalid SharePoint residence-plan folder response")
    folders = content.get("Folders", {}).get("results", [])
    files = content.get("Files", {}).get("results", [])
    if not isinstance(folders, list) or not isinstance(files, list):
        raise ValueError("Invalid SharePoint residence-plan folder contents")
    return files, folders


def _floor_tokens(name: str) -> list[str]:
    stem = Path(name).stem.upper().replace(" ", "")
    suffix = stem.split("-", 1)[1] if "-" in stem else ""
    if suffix in {"BT", "B", "BASEMENT"}:
        return ["basement"]
    if not suffix and "_" in stem:
        suffix = stem.split("_", 1)[1]
    values = []
    for token in re.split(r"[._,]+", suffix):
        if token.isdigit() and len(token) <= 2:
            values.append(token)
        elif len(token) >= 6 and token.isdigit():
            break
    return list(dict.fromkeys(value.zfill(2) for value in values))


def _safe_file_path(root: Path, area: str, building: str, name: str) -> Path:
    safe_parts = [
        re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"
        for value in (area, building, name)
    ]
    return root / safe_parts[0] / safe_parts[1] / safe_parts[2]


def extract_plan_metadata(data: bytes) -> dict:
    """Extract searchable source evidence without pretending it is topology."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Residence-plan parsing requires the pipeline dependencies (pypdf)"
        ) from exc
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    labels = re.findall(r"(?:-\d{2}[A-Z]?|\b\d{3}[A-Z]?\b)", text.upper())
    floor_match = re.search(
        r"\b(GROUND|BASEMENT|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|"
        r"EIGHTH|NINTH|TENTH)\s+FLOOR",
        text.upper(),
    )
    return {
        "page_count": len(reader.pages),
        "floor_label": floor_match.group(1).lower() if floor_match else None,
        "room_labels": list(dict.fromkeys(labels)),
        "has_vertical_circulation": bool(
            re.search(r"\b(?:UP|DN|STAIR|ELEVATOR|LIFT)\b", text.upper())
        ),
        "has_elevator_text": bool(re.search(r"\b(?:ELEVATOR|LIFT)\b", text.upper())),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def inventory_residence_plans(request_context, *, site=SITE, root_folder=ROOT_FOLDER):
    """Recursively return sanitized SharePoint file records."""

    records = []

    def walk(folder, area=None, building=None):
        files, folders = _folder_contents(
            request_context.get(
                _folder_url(site, folder) + "?$expand=Folders,Files",
                headers={"Accept": "application/json;odata=verbose"},
                fail_on_status_code=False,
            )
        )
        for item in files:
            name = str(item.get("Name", "")).strip()
            if not name.lower().endswith(".pdf"):
                continue
            records.append(
                {
                    "area": area,
                    "building": building,
                    "name": name,
                    "server_relative_url": item.get("ServerRelativeUrl"),
                    "size_bytes": int(item.get("Length", 0) or 0),
                    "modified": item.get("TimeLastModified"),
                    "floors": _floor_tokens(name),
                }
            )
        for item in folders:
            child = item.get("ServerRelativeUrl")
            if not child:
                continue
            name = item.get("Name", "")
            walk(child, area if area else name, name if area else None)

    walk(root_folder)
    return sorted(records, key=lambda row: (row["area"] or "", row["building"] or "", row["name"]))


def refresh_residence_plans(
    *,
    storage_state: Path,
    output: Path,
    download_root: Path,
    now: datetime | None = None,
    site=SITE,
    root_folder=ROOT_FOLDER,
):
    """Inventory and download current residence plans using a saved browser session."""

    now = now or datetime.now(UTC)
    saved_state, user_agent = read_session(storage_state, now)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        request = _FreshSharePointClient(playwright, saved_state, user_agent)
        records = inventory_residence_plans(request, site=site, root_folder=root_folder)
        for record in records:
            relative = record["server_relative_url"]
            if not relative:
                raise ValueError(f"SharePoint file has no path: {record['name']}")
            response = request.get(
                _api_url(site, "GetFileByServerRelativeUrl", relative, "/$value"),
                headers={"Accept": "application/pdf"},
                fail_on_status_code=False,
                timeout=60000,
            )
            if response.status != 200:
                raise AuthenticationRequired(
                    f"SharePoint plan download failed (HTTP {response.status})"
                )
            data = response.body()
            destination = _safe_file_path(
                download_root, record["area"], record["building"], record["name"]
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            record["local_path"] = str(destination)
            record["sha256"] = hashlib.sha256(data).hexdigest()
            record["downloaded_bytes"] = len(data)
            record["extracted"] = extract_plan_metadata(data)
    payload = {
        "source": "authenticated_umass_sharepoint_residence_plans",
        "site": site,
        "root_folder": root_folder,
        "observed_at": now.isoformat(),
        "file_count": len(records),
        "building_count": len({(row["area"], row["building"]) for row in records}),
        "records": records,
    }
    atomic_json(output, payload)
    return payload
