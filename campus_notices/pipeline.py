"""Rules first, optional Gemini on abstention, explicit location matching, atomic publish."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .cache import active_closures, atomic_json, read_snapshot, writer_lock
from .models import Location, Notice, PublishedClosure, Snapshot
from .rules import parse_rules
from .sharepoint import load_batch
from .sources import LOCAL_ZONE


def phrase_in(phrase: str, text: str) -> bool:
    phrase = " ".join(phrase.casefold().split())
    text = " ".join(text.casefold().split())
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))


def candidate_locations(notice: Notice, registry: list[Location], *, demo: bool):
    context = f"{notice.building} {notice.text}"
    return [
        loc
        for loc in registry
        if loc.reviewed
        and (demo or not loc.synthetic)
        and any(phrase_in(a, context) for a in loc.building_aliases)
        and any(phrase_in(a, context) for a in loc.asset_phrases)
    ]


def _resolve(notice, impact, candidates, parser_name, now):
    errors = []
    if impact.needs_review:
        errors.append("Parser marked the impact as ambiguous")
    if " ".join(impact.evidence.casefold().split()) not in " ".join(notice.text.casefold().split()):
        errors.append("Evidence is not an exact excerpt of the notice description")
    matches = [
        loc
        for loc in candidates
        if loc.type == impact.type and (impact.location_id is None or loc.id == impact.location_id)
    ]
    if len(matches) != 1:
        errors.append("A unique reviewed asset location is missing")
    if notice.observed_at > now + timedelta(minutes=5):
        errors.append("Source observation timestamp is in the future")
    if impact.status == "working":
        effective = notice.start_time or impact.start_time
        if effective is not None and effective > now:
            errors.append("Restoration is scheduled for the future")
        return None, matches[0] if not errors else None, errors
    errors.extend(notice.issues)
    if notice.start_time and impact.start_time and notice.start_time != impact.start_time:
        errors.append("Extracted start differs from the structured source")
    if notice.end_time and impact.end_time and notice.end_time != impact.end_time:
        errors.append("Extracted end differs from the structured source")
    start, end = notice.start_time or impact.start_time, notice.end_time or impact.end_time
    if start is None:
        errors.append("Missing start date/time")
    if end is None and not (impact.open_ended and phrase_in("until further notice", notice.text)):
        errors.append("Missing end date/time without explicit open-ended wording")
    if start is not None and end is not None and end <= start:
        errors.append("End must be later than start")
    if errors:
        return None, None, errors
    location = matches[0]
    ident = hashlib.sha256(
        f"{notice.id}|{location.id}|{impact.type}|{start}|{end}".encode()
    ).hexdigest()[:24]
    published = PublishedClosure(
        id=ident,
        notice_id=notice.id,
        location_id=location.id,
        asset_id=location.asset_id,
        building_id=location.building_id,
        floor_id=location.floor_id,
        lat=location.lat,
        lng=location.lng,
        radius=location.radius,
        type=impact.type,
        status=impact.status,
        source="official",
        start_time=start,
        end_time=end,
        last_confirmed=notice.observed_at,
        source_id=notice.source_id,
        source_ref=notice.source_ref,
        parser=parser_name,
    )
    return published, None, []


def refresh(
    *,
    sources: list[dict],
    base: Path,
    registry_path: Path,
    output: Path,
    extractor=None,
    now: datetime | None = None,
    demo: bool = False,
    lookahead_days: int = 30,
):
    now = now or datetime.now(UTC)
    status_path = output.with_name(output.stem + ".status.json")
    review_path = output.with_name(output.stem + ".review.json")
    with writer_lock(output):
        try:
            registry = [
                Location.model_validate(item)
                for item in json.loads(registry_path.read_text(encoding="utf-8"))
            ]
            if len({loc.id for loc in registry}) != len(registry):
                raise ValueError("Location IDs must be unique")
            if not sources or len({s["id"] for s in sources}) != len(sources):
                raise ValueError("Provide sources with unique IDs")
            batches = [load_batch(source, base=base, now=now) for source in sources]
            notices = [n for batch in batches for n in batch.notices]
            if len({n.id for n in notices}) != len(notices):
                raise ValueError("Notice IDs must be unique")
            previous = read_snapshot(output) if output.exists() else None
            if previous is not None and previous.synthetic != demo:
                raise ValueError("Use separate snapshot paths for real and synthetic data")
            older_sources = set()
            if previous:
                for batch in batches:
                    observed = previous.source_observed_at.get(batch.source_id)
                    if observed and observed > batch.state.observed_at:
                        older_sources.add(batch.source_id)
                        batch.state = batch.state.model_copy(
                            update={
                                "mode": "cache",
                                "observed_at": observed,
                                "message": "The published snapshot is newer than the fallback. "
                                "Previous closures retained without refreshing their timestamps.",
                            }
                        )
            by_notice = defaultdict(list)
            if previous:
                for closure in previous.closures:
                    if closure.end_time is None or closure.end_time > now:
                        by_notice[closure.notice_id].append(closure)
            counts = Counter(
                imported=len(notices),
                rules=0,
                gemini=0,
                review=0,
                expired=0,
                outside_window=0,
                irrelevant=0,
                restored=0,
            )
            review, restorations = [], []
            today = now.astimezone(LOCAL_ZONE).date()
            for notice in notices:
                if notice.source_id in older_sources:
                    counts["older_ignored"] += 1
                    continue
                ended = notice.end_time is not None and notice.end_time <= now
                ended_day = notice.ends_on is not None and notice.ends_on < today
                started = notice.start_time is None or notice.start_time <= now
                started_day = notice.starts_on is None or notice.starts_on <= today
                if (ended and started) or (ended_day and started_day):
                    counts["expired"] += 1
                    by_notice.pop(notice.id, None)
                    continue
                if notice.starts_on and notice.starts_on > today + timedelta(days=lookahead_days):
                    counts["outside_window"] += 1
                    continue
                candidates = candidate_locations(notice, registry, demo=demo)
                rule = parse_rules(notice)
                extraction, parser_name = rule.extraction, "rules"
                if extraction is None and extractor is not None:
                    extraction = extractor.extract(notice, candidates)
                    parser_name = "gemini"
                if extraction is None:
                    counts["review"] += 1
                    review.append(
                        {
                            "notice_id": notice.id,
                            "source_ref": notice.source_ref,
                            "building": notice.building,
                            "reason": rule.reason,
                            "issues": notice.issues,
                            "text": notice.text,
                            "parser": "unresolved",
                        }
                    )
                    continue
                counts[parser_name] += 1
                if not extraction.relevant:
                    counts["irrelevant"] += 1
                    by_notice.pop(notice.id, None)
                    continue
                pending, issues = [], []
                if not extraction.impacts:
                    issues.append("Relevant notice has no resolved impacts")
                for impact in extraction.impacts:
                    published, restored, errors = _resolve(
                        notice, impact, candidates, parser_name, now
                    )
                    issues.extend(errors)
                    if published:
                        pending.append(published)
                    if restored:
                        effective = notice.start_time or impact.start_time or notice.observed_at
                        restorations.append(
                            (notice.source_id, restored.id, notice.observed_at, effective)
                        )
                        counts["restored"] += 1
                if issues:
                    counts["review"] += 1
                    review.append(
                        {
                            "notice_id": notice.id,
                            "source_ref": notice.source_ref,
                            "building": notice.building,
                            "reason": extraction.reason,
                            "issues": sorted(set(issues)),
                            "text": notice.text,
                            "parser": parser_name,
                            "extraction": extraction.model_dump(mode="json"),
                        }
                    )
                    # Keep the previous known closures for an unresolved revision, without
                    # updating their confirmation timestamps. New valid impacts can coexist.
                    pending = list({c.id: c for c in [*by_notice[notice.id], *pending]}.values())
                by_notice[notice.id] = pending
            closures = [c for group in by_notice.values() for c in group]
            closures = [
                c
                for c in closures
                if not any(
                    c.source_id == source
                    and c.location_id == loc
                    and c.last_confirmed <= observed
                    and c.start_time <= effective
                    for source, loc, observed, effective in restorations
                )
            ]
            observed = {batch.source_id: batch.state.observed_at for batch in batches}
            counts["published"] = len(closures)
            snapshot = Snapshot(
                generated_at=now,
                synthetic=demo,
                closures=closures,
                counts=dict(counts),
                sources=[s["id"] for s in sources],
                source_observed_at=observed,
                source_status={batch.source_id: batch.state for batch in batches},
            )
            counts["active"] = len(active_closures(snapshot, now))
            snapshot.counts = dict(counts)
            atomic_json(review_path, {"generated_at": now.isoformat(), "items": review})
            atomic_json(output, snapshot.model_dump(mode="json"))
            # Derived contract file for the database teammate. Snapshot remains authoritative.
            export_path = output.with_name(output.stem.replace("snapshot", "closures") + ".json")
            if export_path != output:
                atomic_json(export_path, [c.model_dump(mode="json") for c in closures])
            atomic_json(
                status_path,
                {
                    "status": "fallback"
                    if any(b.state.mode in ("cache", "spreadsheet_fallback") for b in batches)
                    else "success",
                    "attempted_at": now.isoformat(),
                    "gemini_calls": getattr(extractor, "calls", 0),
                    "gemini_cache_hits": getattr(extractor, "cache_hits", 0),
                },
            )
            return snapshot
        except Exception as exc:
            atomic_json(
                status_path,
                {
                    "status": "failed",
                    "attempted_at": now.isoformat(),
                    "error_type": type(exc).__name__,
                    "message": "Refresh failed; inspect source access, configuration, "
                    "or Gemini availability. Previous snapshot retained.",
                },
            )
            raise
