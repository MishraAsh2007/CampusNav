"""Normalize official notices. Live SharePoint ingestion lives in sharepoint.py."""

import csv
import hashlib
import io
import json
import re
from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from .models import Notice

LOCAL_ZONE = ZoneInfo("America/New_York")
MAX_BYTES = 15 * 1024 * 1024


class SourceError(ValueError):
    pass


def clean_text(value) -> str:
    text = "" if value is None else str(value)
    if "<" in text and ">" in text:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email removed]", text)
    text = re.sub(
        r"(?<!\d)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", "[phone removed]", text
    )
    return " ".join(text.split())


def source_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        from openpyxl.utils.datetime import from_excel

        result = from_excel(value)
        if isinstance(result, datetime):
            return result.date()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError("Unrecognized date")


def source_time(value) -> time:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, (int, float)) and 0 <= value < 1:
        seconds = round(value * 86400)
        return time(seconds // 3600 % 24, seconds // 60 % 60, seconds % 60)
    text = str(value or "").strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError("Missing or ambiguous clock time")


def local_datetime(day, clock) -> datetime | None:
    day = source_date(day)
    if day is None:
        return None
    wall = datetime.combine(day, source_time(clock))
    local = wall.replace(tzinfo=LOCAL_ZONE)
    if local.utcoffset() != wall.replace(tzinfo=LOCAL_ZONE, fold=1).utcoffset():
        raise ValueError("Ambiguous or nonexistent daylight-saving time")
    if local.astimezone(UTC).astimezone(LOCAL_ZONE).replace(tzinfo=None) != wall:
        raise ValueError("Nonexistent local time")
    return local.astimezone(UTC)


def _table_notices(rows, source_id, source_ref, observed_at, *, allow_empty=False):
    iterator = iter(rows)
    try:
        headers = [str(v or "").strip() for v in next(iterator)]
    except StopIteration as exc:
        raise SourceError("The source table is empty") from exc
    required = {"DOC ID#", "Building", "Starts", "Start Time", "Ends", "End Time", "Desc"}
    if not required.issubset(headers):
        raise SourceError(
            "Expected the UMass notice export headers: " + ", ".join(sorted(required))
        )
    notices, seen, content_ids = [], {}, set()
    for row_number, row in enumerate(iterator, start=2):
        record = dict(zip(headers, row, strict=False))
        if not record.get("DOC ID#"):
            continue
        issues, dates, times = [], {}, {}
        for key, date_col, time_col in (
            ("start", "Starts", "Start Time"),
            ("end", "Ends", "End Time"),
        ):
            try:
                dates[key] = source_date(record.get(date_col))
                times[key] = local_datetime(record.get(date_col), record.get(time_col))
            except ValueError as exc:
                times[key] = None
                issues.append(f"{key}: {exc}")
        # The live list and Excel render dates differently. Use parsed values so a
        # fallback does not create a second identity for the same notice.
        identity = "|".join(
            [
                clean_text(record.get("Building")),
                str(dates.get("start") or record.get("Starts") or ""),
                str(times.get("start") or record.get("Start Time") or ""),
            ]
        )
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:12]
        ident = f"{source_id}:{record['DOC ID#']}:{suffix}"
        description = clean_text(record.get("Desc"))
        categories = clean_text(
            "; ".join(
                str(record.get(k) or "")
                for k in (
                    "Building Safety Security",
                    "HVAC",
                    "Power Electrical",
                    "Water Plumbing",
                    "Other Service",
                )
            )
        )
        notice = Notice(
            id=ident,
            source_id=source_id,
            source_ref=f"{source_ref}:row{row_number}",
            building=clean_text(record.get("Building")),
            text=description,
            categories=categories,
            observed_at=observed_at,
            start_time=times.get("start"),
            end_time=times.get("end"),
            starts_on=dates.get("start"),
            ends_on=dates.get("end"),
            issues=issues,
        )
        canonical = notice.model_dump_json(exclude={"source_ref", "id", "issues"})
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        if digest in content_ids:
            continue
        content_ids.add(digest)
        if ident in seen:
            issue = "Conflicting rows share the same document, building, and start time"
            if issue not in seen[ident].issues:
                seen[ident].issues.append(issue)
            notice.issues.append(issue)
            notice.id += ":" + digest
        else:
            seen[ident] = notice
        if notice.start_time and notice.end_time and notice.end_time <= notice.start_time:
            notice.issues.append("End date/time is not after start date/time")
        notices.append(notice)
    if not notices and not allow_empty:
        raise SourceError("No notice rows found; refusing to replace a previous snapshot")
    return notices


def extract_html(data: bytes, selector: str = "main") -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for element in soup.select("script,style,nav,header,footer,form,noscript"):
        element.decompose()
    main = soup.select_one(selector) or soup.find("article") or soup.body or soup
    text = clean_text(main.get_text(" ", strip=True))
    if re.search(
        r"sign in to your account|enter your password|sign in with your organizational", text, re.I
    ):
        raise SourceError("Source requires sign-in; use the downloaded export")
    return text


def extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or len(reader.pages) > 100:
        raise SourceError("Use an unencrypted notice PDF of at most 100 pages")
    text = clean_text("\n".join(page.extract_text() or "" for page in reader.pages))
    if not text:
        raise SourceError("PDF has no extractable text; OCR or a text export is needed")
    return text


def load_source(spec: dict, *, base: Path, now: datetime, client=None) -> list[Notice]:
    source_id = spec["id"]
    kind = spec["kind"]
    if kind == "url":
        url = spec["url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise SourceError("Notice URLs must use HTTPS without embedded credentials")
        owns_client = client is None
        client = client or httpx.Client(timeout=30, follow_redirects=False)
        try:
            with client.stream(
                "GET", url, headers={"User-Agent": "CampusNavigation/0.1"}
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308, 401, 403):
                    raise SourceError(
                        "Source redirects or requires sign-in; use its export or final URL"
                    )
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise SourceError("Source exceeds 15 MB")
                data = bytes(content)
                kind = "pdf" if "pdf" in response.headers.get("content-type", "") else "html"
        finally:
            if owns_client:
                client.close()
        source_ref, observed = url, now
    else:
        path = Path(spec["path"])
        if not path.is_absolute():
            path = base / path
        if path.stat().st_size > MAX_BYTES:
            raise SourceError("Source exceeds 15 MB")
        data = path.read_bytes()
        source_ref = path.name
        # Re-importing the same export must not pretend its information was reconfirmed now.
        observed = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    if kind == "xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            sheet = workbook[spec["sheet"]] if spec.get("sheet") else workbook.active
            return _table_notices(
                sheet.iter_rows(values_only=True),
                source_id,
                f"{source_ref}:{sheet.title}",
                observed,
            )
        finally:
            workbook.close()
    if kind == "csv":
        return _table_notices(
            csv.reader(io.StringIO(data.decode("utf-8-sig"))), source_id, source_ref, observed
        )
    if kind == "json":
        payload = json.loads(data)
        if not isinstance(payload, list) or not payload:
            raise SourceError("Normalized notice JSON must contain a nonempty list")
        return [
            Notice.model_validate(
                {
                    **r,
                    "id": f"{source_id}:{r['id']}",
                    "source_id": source_id,
                    "source_ref": source_ref,
                    "observed_at": r.get("observed_at", observed),
                }
            )
            for r in payload
        ]
    if kind == "html":
        text = extract_html(data, spec.get("selector", "main"))
    elif kind == "pdf":
        text = extract_pdf(data)
    elif kind == "text":
        text = clean_text(data.decode("utf-8-sig"))
    else:
        raise SourceError(f"Unsupported source kind: {kind}")
    if not text or len(text) > 60000:
        raise SourceError("Notice text is empty or exceeds 60,000 characters")
    # Stable per-document ID lets later revisions replace the same notice.
    ident = hashlib.sha256(source_ref.encode()).hexdigest()[:16]
    return [
        Notice(
            id=f"{source_id}:{ident}",
            source_id=source_id,
            source_ref=source_ref,
            building=spec.get("building", ""),
            text=text,
            observed_at=observed,
        )
    ]
