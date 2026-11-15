"""Parse the UMass Service Interruption Notices (SIN) CSV export into clean JSON.

    python parse_sin.py                                   # closures active right now
    python parse_sin.py --at 2026-01-15T09:00             # closures active at a given local time
    python parse_sin.py --csv path/to/export.csv --refresh-gis

Outputs (in data/out/, git-ignored):
  sin_notices.json       every notice, normalized: times, buildings, category, severity
  closures_official.json elevator_out closures active at --at, in the routing Closure contract

Policy
  * Any notice that says an elevator "may be unavailable", is out, or is in a
    building losing all power BLOCKS that building's elevators for its time window.
  * "Partial" notices (one car at a time, other car stays in service) also block by
    default because the notices rarely say which car; pass --skip-partial to keep them open.
  * Freight-only elevator work does not block passenger elevators (--include-freight to change).
  * Staff names and phone numbers are dropped (phone numbers are also scrubbed from text).

Rule-based on purpose: notices it cannot place (unknown building, repaired dates) carry
"flags" so a later Gemini pass can review them without being on the critical path.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from umass_gis import DATA_DIR, load_gis, write_json_atomic

TZ = ZoneInfo("America/New_York")
DEFAULT_CSV = DATA_DIR / "raw" / "Service_Interruption_Notices.csv"
OUT_DIR = DATA_DIR / "out"
ELEVATOR_RADIUS_M = 10.0
MAX_BUILDING_RADIUS_M = 150.0

# ----------------------------------------------------------------- regexes
ELEVATOR_RX = re.compile(r"\belevators?\b|\bcar\s*\(s\)|\bcars?\s*#?\d|\bsuper car\b|\bdumbwaiter\b", re.I)
ELEVATOR_NEGATED_RX = re.compile(
    r"elevators?\s+will\s+not\s+be\s+(?:interrupted|affected)|not\s+for\s+the\s+[^.]{0,40}elevators", re.I
)
PARTIAL_RX = re.compile(
    r"only\s+one\s+(?:car|elevator)|one\s+car\s+will\s+be\s+(?:down|out)|one\s+car\s+at\s+a\s+time"
    r"|(?:other|#?\d+)\s+car\s+will\s+be\s+running|will\s+(?:still\s+be|remain)\s+in\s+service",
    re.I,
)
INTERMITTENT_RX = re.compile(r"intermittent|may\s+be\s+(?:unavailable|lost)|brief", re.I)
FREIGHT_RX = re.compile(r"\bfreight\b", re.I)
PASSENGER_RX = re.compile(r"\bpassenger\b|\bmain\b", re.I)
ACCESS_OTHER_RX = re.compile(
    r"automatic\s+door|door\s+openers?|\bentrance\b|exterior\s+door|wheelchair|handicapped\s+lift"
    r"|hallway\s+will\s+be\s+(?:closed|blocked)|hallway\s+.{0,20}closed|\bescalators?\b"
    r"|restrooms?\s+(?:will\s+be\s+)?closed|restroom\s+use",
    re.I,
)
CANCELLED_RX = re.compile(r"\bcancell?ed\b", re.I)
UNCANCELLED_RX = re.compile(r"\bun\W*cancell?ed\b", re.I)
SUPERSEDED_RX = re.compile(r"^\s*revised\b.*new\s+sin", re.I)
REPLACES_RX = re.compile(r"replaces\s+sin\s*#?\s*(\d+)", re.I)
WITHDRAWN_RX = re.compile(r"doc\s*id\s*#?\s*0*(\d+)\s+has\s+been\s+withdrawn", re.I)
PHONE_RX = re.compile(r"\(?\b\d{3}\)?[\s.\-=]*\d{3}[\s.\-=]*\d{4}\b")
TIME_RX = re.compile(r"(\d{1,2})(?::?(\d{2}))?(am|pm|a|p|noon)?")

# ------------------------------------------------------- building matching
STOPWORDS = {
    "hall", "halls", "house", "building", "bldg", "laboratory", "laboratories", "lab", "labs", "the",
    "of", "for", "elevator", "elevators", "car", "cars", "all", "areas", "area", "entire", "room",
    "rooms", "rm", "dorm", "dorms", "dc", "dining", "commons", "complex", "will", "be", "impacted", "at",
}
# Normalized CSV spelling -> ArcGIS BuildingName. Checked before fuzzy matching.
ALIASES = {
    "ilc": "Integrative Learning Center",
    "integrative learning center": "Integrative Learning Center",
    "dubois": "DuBois Library", "du bois": "DuBois Library", "library": "DuBois Library",
    "dubois library": "DuBois Library", "library upper 13 floors": "DuBois Library",
    "isb": "Integrated Sciences Building", "integrated science": "Integrated Sciences Building",
    "integrated science building": "Integrated Sciences Building",
    "lsl": "Life Science Laboratories", "life science": "Life Science Laboratories",
    "life sciences": "Life Science Laboratories",
    "psb": "Physical Sciences Building", "physical science": "Physical Sciences Building",
    "physical sciences": "Physical Sciences Building",
    "csb": "Computer Science", "computer science": "Computer Science",
    "uhs": "University Health Center - UHC", "uhc": "University Health Center - UHC",
    "university health services": "University Health Center - UHC",
    "university health center": "University Health Center - UHC",
    "umpd": "Police Station", "umass police": "Police Station", "umass police station": "Police Station",
    "fac": "The Randolph W. Bromery Center for the Arts", "fine arts center": "The Randolph W. Bromery Center for the Arts",
    "bromery": "The Randolph W. Bromery Center for the Arts",
    "isom": "Isenberg School of Management Building", "isenberg": "Isenberg School of Management Building",
    "isenberg school management": "Isenberg School of Management Building",
    "alfond": "Alfond Hall",
    "lgrt": "Lederle Graduate Research Center", "lgrc": "Lederle Graduate Research Center",
    "lederle": "Lederle Graduate Research Center", "lederle graduate research center": "Lederle Graduate Research Center",
    "jqa": "Adams, John Q. House", "john quincy adams": "Adams, John Q. House", "john q adams": "Adams, John Q. House",
    "john adams": "Adams, John House",
    "chc": "Commonwealth Honors College", "honors college": "Commonwealth Honors College",
    "commonwealth honors college": "Commonwealth Honors College", "honors a1": "Commonwealth Honors College",
    "e lab 2": "Engineering Laboratory II", "elab 2": "Engineering Laboratory II", "elab ii": "Engineering Laboratory II",
    "engineering 2": "Engineering Laboratory II", "engineering ii": "Engineering Laboratory II",
    "campus center": "Lincoln Campus Center", "lincoln campus center": "Lincoln Campus Center",
    "lcc": "Lincoln Campus Center",
    "mullins": "Mullins Memorial Center", "mullins center": "Mullins Memorial Center",
    "hampden": "Hampden Dining_Hall",
    "franklin": "Franklin Dining Hall", "worcester": "Worcester Commons",
    "goodell": "Goodell Building",
    "olver design": "Olver, John W. Design Building", "design": "Olver, John W. Design Building",
    "john olver design": "Olver, John W. Design Building", "olver": "Olver, John W. Design Building",
    "champions center": "Kennedy, John Francis Champions Center",
    "mcguirk press box": "Gladchuck Press Box", "gladchuck press box": "Gladchuck Press Box",
    "football performance": "Football Performance Center", "football performance center": "Football Performance Center",
    "marching band": "Parks, George N. Minuteman Marching Band Building",
    "parks marching band": "Parks, George N. Minuteman Marching Band Building",
    "totman": "Totman Physical Education Building", "totman gym": "Totman Physical Education Building",
    "boyden": "Boyden Gymnasium", "boyden gym": "Boyden Gymnasium", "boyden gymnasium": "Boyden Gymnasium",
    "curry hicks": "Hicks Physical Education Building", "curry hicks cage": "Hicks Physical Education Cage",
    "hicks cage": "Hicks Physical Education Cage",
    "tobin": "Tobin Hall",
    "472 north pleasant": "472 North Pleasant Street", "472 north pleasant st": "472 North Pleasant Street",
    "472 north pleasant street": "472 North Pleasant Street", "old newman": "472 North Pleasant Street",
    "newman center 472 north pleasant": "472 North Pleasant Street",
    "358 north pleasant": "358 North Pleasant", "358 n pleasant st": "358 North Pleasant",
    "studio arts": "Studio Arts Building", "physical plant": "Physical Plant Building",
    "70 butterfield terrace": "International Programs", "international programs": "International Programs",
    "ipo": "International Programs", "research admin": "International Programs",
    "conte": "Conte Polymer Research Center", "conte polymer": "Conte Polymer Research Center",
    "knowles": "Knowles Engineering Building", "knowles engineering": "Knowles Engineering Building",
    "goessman": "Goessmann Laboratory", "goessmann": "Goessmann Laboratory",
    "thompson": "Thompson Hall", "whitmore": "Whitmore Hall", "whitmore north south": "Whitmore Hall",
    "south college": "South College", "student union": "Student Union", "recreation center": "Recreation Center",
    "paige": "Paige Laboratory", "paige new": "Paige Laboratory", "hasbrouck": "Hasbrouck Laboratory",
    "morrill i": "Morrill Science Center I", "morrill 1": "Morrill Science Center I",
    "morrill ii": "Morrill Science Center II", "morrill 2": "Morrill Science Center II",
    "morrill iii": "Morrill Science Center III", "morrill 3": "Morrill Science Center III",
    "morrill iv": "Morrill Science Center IV", "morrill 4": "Morrill Science Center IV",
    "morrill iv n": "Morrill Science Center IV", "morrill iv s": "Morrill Science Center IV",
    "morrill 4n": "Morrill Science Center IV", "morrill 4 south": "Morrill Science Center IV",
    "morrill iv north": "Morrill Science Center IV", "morrill iv south": "Morrill Science Center IV",
    "morrill iv n s": "Morrill Science Center IV",
    "old chapel": "Chapel", "ag engineering central": "Agricultural Engineering Building Central",
    "central heating plant": "Central Heating Plant", "chp": "Central Heating Plant",
    "north chiller plant": "North Chiller Plant",
    "grc": "Lederle Graduate Research Center",
    "bromery center": "The Randolph W. Bromery Center for the Arts",
    "bromery concert": "The Randolph W. Bromery Center for the Arts",
    "bromery fine arts center": "The Randolph W. Bromery Center for the Arts",
    "fac bromery": "The Randolph W. Bromery Center for the Arts",
    "mcguirk performance": "Football Performance Center",
    "sphhs hub": "Totman Physical Education Building",
    "hick cage": "Hicks Physical Education Cage",
    "pvta bus facility": "PVTA Bus Garage", "pvta maintenance garage": "PVTA Bus Garage",
}
# Group names that mean several buildings.
MULTI_ALIASES = {
    "morrill": ["Morrill Science Center I", "Morrill Science Center II", "Morrill Science Center III",
                "Morrill Science Center IV"],
    "north resident housing": ["North A", "North B", "North C", "North D"],
    "north dorms a b c and d": ["North A", "North B", "North C", "North D"],
}
# Buildings missing from the 2022 GIS data (e.g. CSL opened later) stay unmatched and are
# flagged rather than guessed.
NUMERAL_RX = re.compile(r"^(?:[ivx]+|\d+)\s*[nsew]?$")


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("+", " ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOPWORDS)


class BuildingIndex:
    def __init__(self, gis: dict):
        self.by_name = {b["name"]: b for b in gis["buildings"]}
        self.aliases = {_norm(k): v for k, v in ALIASES.items() if v in self.by_name}
        self.norm_to_name: dict[str, str] = {}
        for name in self.by_name:
            self.norm_to_name.setdefault(_norm(name), name)
        # "Adams, John House" style names: also index the "John Adams" order.
        for name in self.by_name:
            if "," in name:
                last, first = (p.strip() for p in name.split(",", 1))
                self.norm_to_name.setdefault(_norm(f"{first} {last}"), name)
        self.tokens = {n: set(k.split()) for k, n in self.norm_to_name.items()}
        # Keys shared by several buildings once "hall"/"house"/"dining" are stripped,
        # e.g. "berkshire" -> Berkshire House (dorm) and Berkshire Dining Hall.
        groups: dict[str, list[str]] = {}
        for name in self.by_name:
            groups.setdefault(_norm(name), []).append(name)
        self.ambiguous = {k: v for k, v in groups.items() if len(v) > 1}
        self.ambiguous_hits: list[str] = []

    def _disambiguate(self, key: str, raw: str) -> str:
        names, low = self.ambiguous[key], raw.lower()
        def pick(word):
            return next((n for n in names if word in n.lower()), None)
        if re.search(r"\bdining\b|\bdc\b|\bcommons\b|\bkitchen", low) and pick("dining"):
            return pick("dining")
        if re.search(r"\bhouse\b", low) and pick("house"):
            return pick("house")
        if re.search(r"\bhall\b", low):
            hall = next((n for n in names if n.lower().endswith(" hall") and "dining" not in n.lower()), None)
            if hall:
                return hall
        self.ambiguous_hits.append(raw)
        return sorted(names)[0]

    def _exact(self, k: str, raw: str) -> Optional[str]:
        if k in self.ambiguous:
            return self._disambiguate(k, raw)
        return self.aliases.get(k) or self.norm_to_name.get(k)

    def match_one(self, raw: str) -> Optional[str]:
        """Longest leading-word match (alias or exact), then unique token containment, then fuzzy."""
        key = _norm(raw)
        if not key:
            return None
        words = key.split()
        for i in range(len(words), 0, -1):  # "campus center floors 1 through 12" -> "campus center"
            hit = self._exact(" ".join(words[:i]), raw)
            if hit:
                return hit
        want = set(words)
        holders = {n for n, toks in self.tokens.items() if want <= toks}
        if len(holders) == 1:  # "mahar" -> "Mahar Auditorium"
            return holders.pop()
        for cand in (key, " ".join(words[:2]), words[0]):
            hit = difflib.get_close_matches(cand, list(self.norm_to_name), n=1, cutoff=0.88)
            if hit and len(cand) >= 5:
                return self.norm_to_name[hit[0]]
        return None

    def match(self, field_value: str) -> tuple[list[str], list[str], str]:
        """Return (matched building names, unmatched pieces, area text)."""
        text = re.sub(r"\s+", " ", field_value.replace("\n", " ")).strip()
        text = re.sub(r"\s*-\s*(?:un\W*)?cancell?ed\b.*$", "", text, flags=re.I)
        text = re.sub(r"\s*-\s*change of date.*$|\s*-\s*change\s*$|\s*-\s*proposed date only\s*$", "", text, flags=re.I)
        head, _, area = text.partition(" / ")
        if not area:
            head, _, area = text.partition(" - ")
        head = re.sub(r"\(.*?\)", " ", head)
        multi = MULTI_ALIASES.get(_norm(head))
        if multi:
            return [n for n in multi if n in self.by_name], [], area.strip()
        whole = self.match_one(head)
        pieces = [p.strip() for p in re.split(r"/|,|&|\band\b|\bplus\b", head) if p.strip()]
        found, missing = [], []
        if len(pieces) > 1 or not whole:
            prefix = ""
            for p in pieces:
                if prefix and NUMERAL_RX.match(p.lower().lstrip("#")):
                    p = f"{prefix} {p}"  # "Morrill 1, 2, 3" -> "Morrill 2", "Morrill 3"
                else:
                    toks = p.split()
                    prefix = " ".join(toks[:-1]) if len(toks) > 1 and NUMERAL_RX.match(toks[-1].lower().lstrip("#")) else p
                m = self.match_one(p)
                (found if m else missing).append(m or p)
        if not found and whole:
            found, missing = [whole], []
        found = self._prefer_houses_in_dorm_lists(list(dict.fromkeys(found)))
        return found, missing, area.strip()

    def _prefer_houses_in_dorm_lists(self, found: list[str]) -> list[str]:
        """In 'Field/Webster/Dickinson', Dickinson is the dorm (House), not Dickinson Hall."""
        if len(found) < 2:
            return found
        out = []
        for name in found:
            group = self.ambiguous.get(_norm(name))
            others = [n for n in found if n != name]
            house = next((n for n in group or [] if n.endswith("House")), None)
            if house and sum(n.endswith("House") for n in others) * 2 >= len(others):
                name = house
            out.append(name)
        return list(dict.fromkeys(out))


# ------------------------------------------------------------- date / time
def parse_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date() if s else None
    except ValueError:
        return None


def parse_time(s: str, role: str) -> Optional[time]:
    """Handles '8:00 am', '0700', '800', '7am-3pm', '3;00 PM', '6:00a', '12:00 noon', bare '8:00'."""
    s = (s or "").strip().lower().replace("a.m.", "am").replace("p.m.", "pm")
    s = s.replace(";", ":").replace(".", ":").replace(" ", "")
    if not s:
        return None
    if "-" in s:
        parts = [p for p in s.split("-") if p]
        s = parts[0] if role == "start" else parts[-1]
    m = TIME_RX.fullmatch(s)
    if not m:
        return None
    h, mins, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    leading_zero_24h = len(m.group(1)) == 2 and m.group(1).startswith("0") and not mer and ":" not in s
    if h > 23 or mins > 59:
        return None
    if h >= 13 or leading_zero_24h:
        pass  # already 24-hour
    elif mer in ("pm", "p", "noon"):
        h = h % 12 + 12
    elif mer in ("am", "a"):
        h = h % 12
    elif 1 <= h <= 6:
        h += 12  # bare "2:00" in a work schedule means 2 PM
    return time(h, mins)


def resolve_window(row: dict, flags: list[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    sd, ed = parse_date(row["Starts"]), parse_date(row["Ends"])
    st, et = parse_time(row["Start Time"], "start"), parse_time(row["End Time"], "end")
    if sd is None and ed is None:
        flags.append("no_dates")
        return None, None
    if sd is None:
        sd = ed
        flags.append("start_date_missing")
    if ed is None:
        ed = sd
        flags.append("end_date_missing")
    if st is None:
        st = time(0, 0)
        flags.append("start_time_unparsed")
    if et is None:
        et = time(23, 59)
        flags.append("end_time_unparsed")

    start = datetime.combine(sd, st, TZ)
    end = datetime.combine(ed, et, TZ)
    if end <= start and ed.year < sd.year:
        end = end.replace(year=sd.year)
        flags.append("end_year_fixed")
    if end <= start and ed == sd and et.hour < 12 and (et.hour + 12) * 60 + et.minute > st.hour * 60 + st.minute:
        end = datetime.combine(sd, time(et.hour + 12, et.minute), TZ)
        flags.append("end_meridiem_fixed")
    if end <= start and end.date() < start.date():
        end = datetime.combine(sd, et, TZ)
        flags.append("end_date_fixed")
    if end <= start and end.date() == start.date():  # "9:00pm" to "5:00am" on the same date = overnight
        end += timedelta(days=1)
        flags.append("end_rolled_overnight")
    if end <= start:
        end = start + timedelta(hours=1)
        flags.append("end_defaulted")
    return start, end


# ---------------------------------------------------------- classification
@dataclass
class Notice:
    doc_id: str
    building_raw: str
    area: str
    buildings: list[str]
    unmatched: list[str]
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    categories: list[str]
    severity: Optional[str]
    scope: Optional[str]
    description: str
    systems: dict
    dept: str
    status: str = "scheduled"
    flags: list[str] = field(default_factory=list)
    car_scope: str = "one"          # all | one | cars (which elevator cars the notice takes out)
    cars: list[int] = field(default_factory=list)

    def to_json(self) -> dict:
        d = self.__dict__.copy()
        d["starts_at"] = self.starts_at.isoformat() if self.starts_at else None
        d["ends_at"] = self.ends_at.isoformat() if self.ends_at else None
        return d


def classify(row: dict) -> tuple[list[str], Optional[str], Optional[str]]:
    text = " ".join(row[k] for k in ("Building", "Desc", "Other Service"))
    safety, power = row["Building Safety Security"], row["Power Electrical"]
    cats: list[str] = []

    mentions = bool(ELEVATOR_RX.search(text)) or "Elevators" in safety
    if mentions and not ELEVATOR_NEGATED_RX.search(text):
        cats.append("elevator")
    if "All Building Electrical" in power:
        cats.append("building_power")
    if ACCESS_OTHER_RX.search(text):
        cats.append("access_other")

    if not ({"elevator", "building_power"} & set(cats)):
        return cats or ["other"], None, None

    if "elevator" in cats and PARTIAL_RX.search(text):
        severity = "partial"
    elif INTERMITTENT_RX.search(text):
        severity = "may_be_unavailable"
    else:
        severity = "out"

    # Non-passenger work: the Building field names a freight car, or it's a dumbwaiter test.
    building = row["Building"]
    scope = "passenger"
    if "building_power" not in cats and (
        (FREIGHT_RX.search(building) and not PASSENGER_RX.search(building)) or re.search(r"dumbwaiter", text, re.I)
    ):
        scope = "freight"
    return cats, severity, scope


ALL_CARS_RX = re.compile(r"\ball\s+(?:\w+\s+|\(\d+\)\s+){0,3}(?:elevators?|cars?)\b|\bevery\s+(?:elevator|car)\b", re.I)
CAR_NUM_RX = re.compile(r"(?:\b(?:cars?|elevators?)\s*(?:\(s\))?\s*(?:#|no\.?)?\s*|#)(\d{1,2})\b(?!\s*(?::|[ap]\.?m\b))", re.I)
CAR_LIST_RX = re.compile(r"^\s*(?:,|and|&|\+)\s*#?(\d{1,2})\b(?!\s*(?::|[ap]\.?m\b))", re.I)
CAR_RANGE_RX = re.compile(r"^\s*(?:through|thru|to|-)\s*#?(\d{1,2})\b(?!\s*(?::|[ap]\.?m\b))", re.I)


def derive_car_scope(cats: list[str], severity: Optional[str], text: str) -> tuple[str, list[int]]:
    """Which cars a notice takes out: ("all", []), ("one", []) or ("cars", [numbers])."""
    if "building_power" in cats:
        return "all", []
    if ALL_CARS_RX.search(text):
        return "all", []
    nums: list[int] = []
    for m in CAR_NUM_RX.finditer(text):
        nums.append(int(m.group(1)))
        rest = text[m.end():]
        while True:
            r = CAR_RANGE_RX.match(rest)
            if r and int(r.group(1)) > nums[-1]:
                nums.extend(range(nums[-1] + 1, int(r.group(1)) + 1))
                rest = rest[r.end():]
                continue
            li = CAR_LIST_RX.match(rest)
            if li:
                nums.append(int(li.group(1)))
                rest = rest[li.end():]
                continue
            break
    nums = sorted(set(n for n in nums if 0 < n <= 20))
    if nums:
        return "cars", nums
    return "one", []


def _clean(s: str) -> str:
    return PHONE_RX.sub("[phone removed]", re.sub(r"\s+", " ", s or "")).strip()


def parse_csv(path: Path, index: BuildingIndex) -> list[Notice]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    by_id: dict[str, dict] = {}
    for r in rows:  # later duplicate rows win (the export appends corrections)
        r = {k: (v or "").strip() for k, v in r.items()}
        by_id[r["DOC ID%23"]] = r

    superseded: set[str] = set()
    for r in by_id.values():
        blob = " ".join(r.values())
        superseded.update(REPLACES_RX.findall(blob))
        superseded.update(WITHDRAWN_RX.findall(blob))

    notices = []
    for doc_id, r in by_id.items():
        flags: list[str] = []
        start, end = resolve_window(r, flags)
        cats, severity, scope = classify(r)
        before = len(index.ambiguous_hits)
        car_scope, cars = derive_car_scope(cats, severity, " ".join(r[k] for k in ("Building", "Desc", "Other Service")))
        names, missing, area = index.match(r["Building"])
        if {"elevator", "building_power"} & set(cats) and not names:
            flags.append("building_unmatched")
        if missing and names:
            flags.append("building_partly_unmatched")
        if len(index.ambiguous_hits) > before:
            flags.append("building_ambiguous")

        status = "scheduled"
        label = r["Building"] + " " + r["Desc"]
        if UNCANCELLED_RX.search(label):
            status = "scheduled"
        elif CANCELLED_RX.search(r["Building"]) or (CANCELLED_RX.search(r["Desc"]) and not r["Starts"]):
            status = "cancelled"
        elif SUPERSEDED_RX.search(r["Building"]) or doc_id.lstrip("0") in superseded:
            status = "superseded"

        notices.append(
            Notice(
                doc_id=doc_id,
                building_raw=_clean(r["Building"]),
                area=_clean(area),
                buildings=names,
                unmatched=missing,
                starts_at=start,
                ends_at=end,
                categories=cats,
                severity=severity,
                scope=scope,
                description=_clean(r["Desc"]),
                systems={
                    "safety": _clean(r["Building Safety Security"]),
                    "hvac": _clean(r["HVAC"]),
                    "power": _clean(r["Power Electrical"]),
                    "water": _clean(r["Water Plumbing"]),
                    "other": _clean(r["Other Service"]),
                },
                dept=r["Dept"],
                status=status,
                flags=flags,
                car_scope=car_scope,
                cars=cars,
            )
        )
    notices.sort(key=lambda n: (n.starts_at or datetime.min.replace(tzinfo=TZ), n.doc_id))
    return notices


# ---------------------------------------------------------------- closures
def blocks_elevators(n: Notice, skip_partial: bool, include_freight: bool) -> bool:
    if n.status != "scheduled" or not n.starts_at or not n.buildings:
        return False
    if not ({"elevator", "building_power"} & set(n.categories)):
        return False
    if n.scope == "freight" and not include_freight:
        return False
    if n.severity == "partial" and skip_partial:
        return False
    return True


def _label(n: Notice) -> str:
    if "elevator" not in n.categories:
        return "Building power shutdown; elevators may stop"
    if n.car_scope == "cars" and n.cars:
        nums = ", ".join(f"#{c}" for c in n.cars)
        verb = {"out": "out of service", "partial": "out of service"}.get(n.severity, "may be unavailable")
        return f"Elevator {nums} {verb}"
    return {"out": "Elevator out of service", "partial": "One elevator car out of service"}.get(
        n.severity, "Elevator may be unavailable"
    )


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def scope_token(n: Notice) -> str:
    """Id suffix the routing engine reads back as the closure's scope (see docs/contracts.md)."""
    if n.severity == "partial" and n.car_scope != "all" and len(n.cars) != 1:
        return "one"  # "one car at a time": several named cars are never out together
    if n.car_scope == "cars" and n.cars:
        return "car" + "+".join(str(c) for c in n.cars)
    return n.car_scope


def notice_site(b: dict) -> tuple[float, float, float]:
    """(lat, lon, radius_m) for a notice's single closure in building ``b``.

    The GIS has one marker per lobby, not per car, so a notice no longer gets one closure per
    marker. It sits at the marker nearest the building center, or at the center if none.
    """
    if b["elevators"]:
        clat, clon = b["centroid"]
        e = min(b["elevators"], key=lambda e: (e["lat"] - clat) ** 2 + (e["lon"] - clon) ** 2)
        return e["lat"], e["lon"], ELEVATOR_RADIUS_M
    lat, lon = b["centroid"]
    return lat, lon, min(b["radius_m"] + 5, MAX_BUILDING_RADIUS_M)


def build_closures(
    notices: list[Notice], index: BuildingIndex, at: datetime, confirmed_at: datetime,
    skip_partial: bool = False, include_freight: bool = False,
) -> list[dict]:
    out = []
    for n in notices:
        if not blocks_elevators(n, skip_partial, include_freight) or not (n.starts_at <= at < n.ends_at):
            continue
        when = f"{n.starts_at:%b %d %I:%M %p} to {n.ends_at:%b %d %I:%M %p}".replace(" 0", " ")
        for name in n.buildings:
            b = index.by_name[name]
            base = {
                "type": "elevator_out",
                "description": f"{_label(n)} at {name}, {when} (UMass SIN #{n.doc_id})",
                "reported_at": None,
                "confirmed_at": confirmed_at.isoformat(timespec="seconds"),
                "expires_at": n.ends_at.isoformat(),
                # Extra fields: ignored by the routing engine, useful to the app / Mongo.
                "source": "umass_sin",
                "notice_id": n.doc_id,
                "building": name,
                "starts_at": n.starts_at.isoformat(),
                "severity": n.severity,
            }
            lat, lon, radius = notice_site(b)
            token = scope_token(n)
            out.append({"id": f"sin-{n.doc_id}-{_slug(name)}~{token}", "lat": lat, "lon": lon,
                        "radius_m": radius, "scope": "cars" if token.startswith("car") else token,
                        "cars": n.cars if token.startswith("car") else [], **base})
    return out


# --------------------------------------------------------------------- CLI
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--at", help="local time to evaluate, e.g. 2026-01-15T09:00 (default: now)")
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--skip-partial", action="store_true", help="don't block 'one car at a time' notices")
    p.add_argument("--include-freight", action="store_true", help="also block for freight-only elevator work")
    p.add_argument("--refresh-gis", action="store_true", help="re-download building/elevator data")
    args = p.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 1
    at = datetime.fromisoformat(args.at).replace(tzinfo=TZ) if args.at else datetime.now(TZ)
    exported = datetime.fromtimestamp(args.csv.stat().st_mtime, timezone.utc)

    index = BuildingIndex(load_gis(refresh=args.refresh_gis))
    notices = parse_csv(args.csv, index)
    closures = build_closures(notices, index, at, exported, args.skip_partial, args.include_freight)

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(args.out_dir / "sin_notices.json",
                      {"generated_at": generated, "source_exported_at": exported.isoformat(timespec="seconds"),
                       "notices": [n.to_json() for n in notices]})
    write_json_atomic(args.out_dir / "closures_official.json", closures)

    elev = [n for n in notices if {"elevator", "building_power"} & set(n.categories) and n.status == "scheduled"]
    unmatched = sorted({n.building_raw for n in elev if "building_unmatched" in n.flags})
    fixed = sum(1 for n in notices if any(f.endswith("_fixed") or f == "end_defaulted" for f in n.flags))
    upcoming = [n for n in elev if n.starts_at and n.starts_at > at and blocks_elevators(n, args.skip_partial, args.include_freight)][:5]

    print(f"notices: {len(notices)} unique "
          f"({sum(n.status == 'cancelled' for n in notices)} cancelled, {sum(n.status == 'superseded' for n in notices)} superseded)")
    matched = sum(1 for n in elev if "building_unmatched" not in n.flags)
    print(f"elevator-affecting: {len(elev)} | building matched: {matched} | dates/times repaired: {fixed}")
    print(f"evaluated at {at:%Y-%m-%d %H:%M %Z}: {len(closures)} active closure(s) -> {args.out_dir / 'closures_official.json'}")
    for c in closures[:10]:
        print(f"   {c['id']}: {c['description']}")
    if upcoming:
        print("next elevator-affecting notices:")
        for n in upcoming:
            print(f"   #{n.doc_id} {', '.join(n.buildings)}: {n.starts_at:%a %b %d %I:%M %p} to {n.ends_at:%I:%M %p} [{n.severity}]")
    if unmatched:
        print(f"unmatched buildings on elevator notices ({len(unmatched)}): " + "; ".join(unmatched))
    return 0


if __name__ == "__main__":
    sys.exit(main())
