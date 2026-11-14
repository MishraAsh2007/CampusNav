"""Discover public accessibility reports for review, without publishing routing closures."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
from pydantic import AwareDatetime, Field

from campus_routing.models import ContractModel

from .cache import atomic_json, writer_lock
from .models import Extraction, Location, Notice
from .pipeline import candidate_locations
from .public_sources import NotConfigured, PublicPost, fetch_posts
from .rules import parse_rules
from .sources import SourceError

TOPICS = {
    "elevator": r"\belevators?\b",
    "ramp": r"\bramps?\b",
    "path": r"\b(?:sidewalks?|walkways?|paths?|crosswalks?|entrances?|curb cuts?)\b",
    "accessibility": r"\b(?:accessibility|wheelchair|step.free|accessible entrance)\b",
    "transit": r"\b(?:buses?|bus stops?|transit|pvta|detours?|paratransit)\b",
}


class ExternalReport(ContractModel):
    id: str
    source_id: str
    source_name: str
    source: Literal["official", "community", "publisher"]
    url: str
    title: str
    text: str
    published_at: AwareDatetime | None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    expires_at: AwareDatetime
    topics: list[str]
    location_candidates: list[str]
    parser: Literal["rules", "gemini", "unresolved"]
    extraction: Extraction | None
    review_reasons: list[str]
    review_status: Literal["needs_review"] = "needs_review"
    routing_eligible: Literal[False] = False


class FeedStatus(ContractModel):
    name: str
    state: Literal["live", "cached", "error", "not_configured", "disabled"]
    attempted_at: AwareDatetime
    last_success_at: AwareDatetime | None = None
    fetched_count: int = 0
    message: str = ""


class Observation(ContractModel):
    source_id: str
    first_seen_at: AwareDatetime


class ReportsSnapshot(ContractModel):
    version: Literal[1] = 1
    generated_at: AwareDatetime
    synthetic: bool = False
    reports: list[ExternalReport]
    sources: dict[str, FeedStatus]
    # Keep only IDs/timestamps for expired posts still visible in a feed, preventing
    # an undated old post from appearing newly reported on each refresh.
    observed: dict[str, Observation] = Field(default_factory=dict)


def report_id(item, spec):
    key = item.url + ("#" + item.native_id if spec["kind"] == "pvta" else "")
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def analyze(item, spec, *, first_seen, now, registry, extractor, demo):
    text = f"{item.title}. {item.text}"
    topics = [name for name, pattern in TOPICS.items() if re.search(pattern, text, re.I)]
    campus_terms = spec.get("campus_terms", [])
    if not topics or (
        campus_terms and not any(term.casefold() in text.casefold() for term in campus_terms)
    ):
        return None
    retention = timedelta(hours=float(spec.get("retention_hours", 24)))
    if not timedelta(0) < retention <= timedelta(days=7):
        raise SourceError("retention_hours must be greater than 0 and at most 168")
    # A publication date is not an outage start. It bounds how long we keep this claim.
    reported = item.published_at or first_seen
    expires = min(first_seen + retention, reported + retention)
    if expires <= now or reported > now + timedelta(minutes=5):
        return None
    authority = spec.get("authority", "community")
    notice = Notice(
        id=report_id(item, spec),
        source_id=spec["id"],
        source_ref=item.url,
        text=text,
        observed_at=now,
        source_authority=authority,
        published_at=item.published_at,
    )
    candidates = candidate_locations(notice, registry, demo=demo)
    reasons = ["A discovered report is not a confirmed routing closure."]
    if item.published_at is None:
        reasons.append("Publication time is unknown; first_seen_at is not an outage start time.")
    if not candidates:
        reasons.append("No uniquely reviewed asset location is available.")
    rule = parse_rules(notice, require_interval=False)
    extraction, parser = rule.extraction, "rules"
    if extraction is None and extractor is not None:
        try:
            extraction = extractor.extract(notice, candidates)
            parser = "gemini"
        except Exception as exc:
            reasons.append(
                f"Optional parser unavailable ({type(exc).__name__}); report kept for review."
            )
    if extraction is None:
        parser = "unresolved"
        reasons.append(rule.reason)
    else:
        ids = {loc.id for loc in candidates}
        if any(
            " ".join(impact.evidence.split()).casefold() not in " ".join(text.split()).casefold()
            or (impact.location_id is not None and impact.location_id not in ids)
            for impact in extraction.impacts
        ):
            extraction, parser = None, "unresolved"
            reasons.append("Parser output could not be grounded in the report and known locations.")
        elif extraction.impacts and any(i.needs_review for i in extraction.impacts):
            reasons.append("Impact timing or scope needs review.")
    if "transit" in topics:
        reasons.append("A bus service change does not establish closure of a walking path.")
    return ExternalReport(
        id=notice.id,
        source_id=spec["id"],
        source_name=spec.get("name", spec["id"]),
        source=authority,
        url=item.url,
        title=item.title,
        text=item.text,
        published_at=item.published_at,
        first_seen_at=first_seen,
        last_seen_at=now,
        expires_at=expires,
        topics=topics,
        location_candidates=[loc.id for loc in candidates],
        parser=parser,
        extraction=extraction,
        review_reasons=reasons,
    )


def read_reports(path):
    return ReportsSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))


def active_reports(snapshot, now):
    return [report for report in snapshot.reports if report.expires_at > now]


def reports_status(path, now=None):
    now = now or datetime.now(UTC)
    try:
        snapshot = read_reports(path)
    except (OSError, ValueError):
        return {"status": "unavailable", "stale": True, "report_count": None, "sources": {}}
    usable = any(s.last_success_at is not None for s in snapshot.sources.values())
    live = [s for s in snapshot.sources.values() if s.state != "disabled"]
    stale = now - snapshot.generated_at > timedelta(hours=2) or any(s.state != "live" for s in live)
    return {
        "status": "unavailable" if not usable else ("partial" if stale else "ready"),
        "stale": stale,
        "synthetic": snapshot.synthetic,
        "generated_at": snapshot.generated_at.isoformat(),
        "report_count": len(active_reports(snapshot, now)),
        "sources": {key: state.model_dump(mode="json") for key, state in snapshot.sources.items()},
    }


def refresh_reports(
    *,
    sources,
    output,
    registry_path,
    extractor=None,
    now=None,
    demo=False,
    client=None,
    fetcher=fetch_posts,
):
    now = now or datetime.now(UTC)
    if not sources or len({s["id"] for s in sources}) != len(sources):
        raise SourceError("Provide at least one public source with unique IDs")
    registry = [
        Location.model_validate(row)
        for row in json.loads(registry_path.read_text(encoding="utf-8"))
    ]
    with writer_lock(output):
        previous = read_reports(output) if output.exists() else None
        if previous is not None and previous.synthetic != demo:
            raise SourceError("Real and demonstration reports need separate output paths")
        old_seen = previous.observed if previous else {}
        old_reports = previous.reports if previous else []
        states, reports, observations = {}, {}, {}
        own_client = client is None
        client = client or httpx.Client(timeout=20, follow_redirects=False)
        try:
            for spec in sources:
                sid = spec["id"]
                old_status = previous.sources.get(sid) if previous else None
                status = FeedStatus(name=spec.get("name", sid), state="live", attempted_at=now)
                states[sid] = status
                if spec.get("enabled", True) is False:
                    status.state = "disabled"
                    continue
                try:
                    items = fetcher(spec, client=client)
                    pending, seen = {}, {}
                    for item in items:
                        if not isinstance(item, PublicPost):
                            item = PublicPost.model_validate(item)
                        ident = report_id(item, spec)
                        first = old_seen[ident].first_seen_at if ident in old_seen else now
                        seen[ident] = Observation(source_id=sid, first_seen_at=first)
                        result = analyze(
                            item,
                            spec,
                            first_seen=first,
                            now=now,
                            registry=registry,
                            extractor=extractor,
                            demo=demo,
                        )
                        if result:
                            pending[ident] = result
                    reports.update(
                        {key: value for key, value in pending.items() if key not in reports}
                    )
                    observations.update(seen)
                    status.last_success_at, status.fetched_count = now, len(items)
                except Exception as exc:
                    status.state = "not_configured" if isinstance(exc, NotConfigured) else "error"
                    status.message = (
                        str(exc)
                        if isinstance(exc, SourceError)
                        else f"Source could not be parsed ({type(exc).__name__})"
                    )
                    if old_status and old_status.last_success_at:
                        status.last_success_at = old_status.last_success_at
                        status.state = "cached"
                        for report in old_reports:
                            if report.source_id == sid and report.expires_at > now:
                                reports.setdefault(report.id, report)
                        observations.update(
                            {key: seen for key, seen in old_seen.items() if seen.source_id == sid}
                        )
        finally:
            if own_client:
                client.close()
        result = ReportsSnapshot(
            generated_at=now,
            synthetic=demo,
            reports=list(reports.values()),
            sources=states,
            observed=observations,
        )
        atomic_json(output, result.model_dump(mode="json"))
        return result
