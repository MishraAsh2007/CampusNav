"""A conservative finite-state classifier over regex-recognized notice phrases.

States: no impact, closed, degraded, working, ambiguous. Conflicting signals abstain;
Gemini or a human can then handle the notice. It does not infer geography.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from .models import Extraction, Impact, Notice

PARSER_VERSION = "rules-v2"
TYPES = {
    "elevator": r"\b(?:elevators?|lifts?)\b",
    "ramp": r"\bramps?\b",
    "path": r"\b(?:paths?|sidewalks?|walkways?|crosswalks?|footpaths?|entrances?|egress|"
    r"pedestrian routes?)\b",
}
SIGNALS = {
    "working": r"\b(?:back in service|returned to service|service (?:has been )?restored|"
    r"reopened|operating normally|remains? open|not closed|not blocked)\b",
    "degraded": r"\b(?:limited access|reduced service|partially blocked|intermittent service|"
    r"may be unavailable during (?:the )?(?:test|inspection))\b",
    "closed": r"\b(?:out of service|not working|unavailable|closed|blocked|broken|shut down)\b",
}
UNCERTAIN = re.compile(
    r"\b(?:might|could|possibly|if|unless|one (?:car|elevator) at a time|"
    r"only one|phases?|daily|each day|weekdays|following day)\b",
    re.I,
)
NEGATION = re.compile(r"\b(?:not|never|no|won't|will not|isn't|aren't)\b", re.I)
ISO = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})"


@dataclass(frozen=True)
class RuleResult:
    extraction: Extraction | None
    reason: str


def _window(notice: Notice):
    if notice.start_time is not None:
        return notice.start_time, notice.end_time
    match = re.search(rf"\bfrom\s+({ISO})\s+(?:to|until)\s+({ISO})", notice.text, re.I)
    if match:
        return tuple(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in match.groups())
    return None, None


def _has_asset_subject(prefix: str, kind: str) -> bool:
    """Accept a bounded subject/verb vocabulary, otherwise let the fallback interpret it."""
    pattern = TYPES[kind]
    if kind == "elevator":
        pattern += r"|\bcars?(?:\(s\))?"
    subjects = list(re.finditer(pattern, prefix, re.I))
    if not subjects:
        return False
    tail = prefix[subjects[-1].end() :]
    words = re.findall(r"\w+", tail.casefold())
    allowed = {
        "is",
        "are",
        "will",
        "be",
        "being",
        "has",
        "have",
        "been",
        "remain",
        "remains",
        "temporarily",
        "currently",
        "now",
        "and",
    }
    return all(word in allowed or word.isdigit() for word in words)


def parse_rules(notice: Notice, *, require_interval: bool = True) -> RuleResult:
    context = f"{notice.building} {notice.categories} {notice.text}"
    kinds = [kind for kind, pattern in TYPES.items() if re.search(pattern, context, re.I)]
    if not kinds:
        if re.search(
            r"\b(?:accessible|accessibility|wheelchair|detour|stairs|stairwell)\b", context, re.I
        ):
            return RuleResult(None, "Accessibility mentioned without a supported asset type")
        return RuleResult(
            Extraction(relevant=False, reason="No supported accessibility asset mentioned"),
            "irrelevant",
        )
    if len(kinds) != 1:
        return RuleResult(None, "Multiple asset types require separate impact attribution")
    if not notice.text.strip():
        return RuleResult(None, "No description to establish an outage")
    if UNCERTAIN.search(notice.text):
        return RuleResult(None, "Conditional, phased, or recurring impact")
    # Consume longer phrases first so 'not closed' is not also read as 'closed'.
    remaining = notice.text
    states = set()
    for state in ("working", "degraded", "closed"):
        pattern = re.compile(SIGNALS[state], re.I)
        matches = list(pattern.finditer(remaining))
        for match in matches:
            prefix = remaining[: match.start()]
            # Negation and modality are scoped to the same clause, not a previous sentence.
            clause = re.split(r"[.;!?]", prefix)[-1]
            if NEGATION.search(clause) or re.search(
                r"\b(?:may|might|could|expected)\b", clause, re.I
            ):
                return RuleResult(None, "Negated or uncertain status needs interpretation")
            if not _has_asset_subject(clause, kinds[0]):
                return RuleResult(None, "Status is not clearly attached to the accessibility asset")
        if matches:
            states.add(state)
            remaining = pattern.sub(" ", remaining)
    if len(states) != 1:
        return RuleResult(None, "Conflicting or missing service status")
    status = next(iter(states))
    if status == "working" and re.search(r"\bwill\b", notice.text, re.I):
        return RuleResult(None, "A future restoration is not a current operating confirmation")
    start, end = _window(notice)
    open_ended = bool(re.search(r"\buntil further notice\b", notice.text, re.I))
    missing_interval = start is None or (end is None and not open_ended)
    if require_interval and status != "working" and missing_interval:
        return RuleResult(None, "Missing explicit date/time interval")
    impact = Impact(
        type=kinds[0],
        status=status,
        start_time=start,
        end_time=end,
        open_ended=open_ended,
        evidence=notice.text[:1500],
        needs_review=not require_interval and missing_interval,
    )
    return RuleResult(
        Extraction(relevant=True, impacts=[impact], reason="Unambiguous rule match"), status
    )
