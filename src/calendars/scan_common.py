"""Shared helpers for parsing class-like schedule emails (Gmail/Outlook)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from core.date_utils import MONTH_MAP
from core.text_utils import html_to_text  # noqa: F401 - re-exported for calendars.outlook.commands

TIME_PAT1 = r"(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<ampm1>am|pm|a\.m\.|p\.m\.)?"
TIME_PAT2 = r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<ampm2>am|pm|a\.m\.|p\.m\.)?"
RANGE_PAT = re.compile(
    rf"\b(?P<day>mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b[^\n\r]*?{TIME_PAT1}\s*(?:-|to|–|—)\s*{TIME_PAT2}",
    re.I,
)

_CLASS_PAT_PARTS = [
    r"swimmer\s?[0-9a-z]+",
    r"swim\s?kids\s?\d+",
    r"preschool\s?[a-f]",
    r"bronze\s?(?:star|medallion|cross)",
    r"private\s*lessons?",
]
CLASS_PAT = re.compile(r"\b(" + "|".join(_CLASS_PAT_PARTS) + r")\b", re.I)
LOC_LABEL_PAT = re.compile(r"^\s*(Location|Venue)\s*:\s*(.+)$", re.I | re.M)

# Fallback subject when no activity name can be derived from the email body.
DEFAULT_CLASS_SUBJECT = "Class"

# Registrant names observed are "First Last". Capping the capture at two words
# keeps preceding prose out of the name when the pattern is not label-anchored.
MAX_NAME_WORDS = 2
# Single-letter tokens are initials or stray prose fragments, not usable names.
MIN_NAME_WORD_LEN = 2

# Clock bounds. RANGE_PAT matches digits in prose, so captures outside these
# ranges are proof the match is not a time at all.
MAX_HOUR = 23
MAX_MINUTE = 59

# Longest plausible single session for a recurring kids' class. The real
# "Adventure Series - Adventure Day" runs 13:00-16:00 (3h), and full-day camps
# are advertised as date ranges rather than weekly recurrences, so anything
# beyond 4h is prose that happened to contain two times (a newsletter's
# "9:00 AM - 12:00 PM" camp blurb, an office-hours line) rather than a class.
MAX_SESSION_MINUTES = 4 * 60

# Provider A (City of Richmond Hill / "Active RH" activecommunities receipts):
#   "Order Summary: <registrant> Enrollment in <activity> (# 151046)"
#   "... <registrant> Pending enrollment in <activity> (# 151046)"
# Two details drive this pattern:
#   1. Activity names commonly take a "Category - Variant" shape ("Chess -
#      Intermediate", "Dance - Jazz"), so the internal hyphen is preserved and
#      the capture ends only at the enrollment id, an open paren, or end of line.
#   2. Not-yet-processed registrations read "Pending enrollment in" with a
#      lowercase "e", so the phrase is matched case-insensitively with that
#      optional prefix rather than on a capitalized "Enrollment in" alone.
ACTIVITY_ENROLLMENT_PAT = re.compile(
    r"(?:pending\s+)?enrollment\s+in\s+(?P<activity>[a-z][a-z0-9 &/+\-']*?)"
    r"\s*(?:\(#|\(|\r|\n|$)",
    re.I,
)

# Provider B (WD SWIM Richmond Inc.): "Class: Glider2-3 Sun 9:30AM Lane 5".
# The trailing day/time/lane qualifier is dropped so the subject is the class
# name alone; the day and time are already carried by byday/start_time/end_time.
ACTIVITY_CLASS_LABEL_PAT = re.compile(
    r"Class:\s*(?P<activity>[^\r\n]+?)"
    r"(?=\s+(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*\d|\s*(?:\r|\n)|$)",
    re.I,
)

# Registrant ("child") name patterns, in priority order.
#   Provider B: "Student: Bruce Sherwin"
#   Provider A: "Order Summary: Blass sherwin Enrollment in ..."
#   Provider A (pending):   "... bruce sherwin Pending enrollment in ..."
#   Provider A (processed): "Thank you. Your transaction has been processed.
#                            bennet sherwin Enrollment in ..."
# The Active RH forms anchor on the "[Pending] enrollment in" phrase that
# *follows* the name rather than on an "Order Summary:" label, because the
# processed-transaction variant carries no such label. "Pending" is part of the
# vendor's phrasing, not part of the name, so it sits outside the capture group.
# Structural markers distinguishing an enrollment notice from a broadcast.
STUDENT_LABEL_PAT = re.compile(r"\bStudent:\s*[a-z]", re.I)
SCHEDULE_LABEL_PAT = re.compile(r"\b(?:Schedule|New\s+Time|Old\s+Time):\s*", re.I)
# Multi-week courses read "Meeting Dates: From <d1> to <d2>", but one-off
# sessions (tournaments, single-day adventure trips) read "Meeting Dates:
# <date>" with no range, so the "From" must not be required here.
MEETING_DATES_PAT = re.compile(r"Meeting\s+Dates:\s*\w", re.I)

# Words that never appear in a registrant name but are common in the marketing
# prose that the unanchored Active RH pattern can otherwise match ("...families
# have found enrollment in...", "...sign-up and enrollment in..."). A candidate
# containing any of these is prose, not a name.
NON_NAME_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "by", "can", "for",
        "found", "from", "get", "give", "has", "have", "here", "highest", "how",
        "in", "is", "it", "its", "more", "most", "new", "now", "of", "on", "or",
        "our", "out", "please", "see", "sign", "sign-up", "so", "that", "the",
        "their", "them", "then", "there", "these", "they", "this", "to", "up",
        "use", "was", "we", "were", "what", "when", "which", "who", "will",
        "with", "you", "your",
    }
)

CHILD_PAT_PARTS = [
    # Stop before the next "Label:" token — "Student: Bruce Sherwin Class: ..."
    # would otherwise capture the word "Class" as part of the name.
    re.compile(r"Student:\s*(?P<name>[a-z][a-z\s'\-]*?[a-z])(?=\s+[a-z]+:|\s*[\r\n]|$)", re.I),
    re.compile(
        r"(?P<name>[a-z][a-z\s'\-]*?[a-z])\s+(?:pending\s+)?enrollment\s+in\b", re.I
    ),
    re.compile(r"Registrant:\s*(?:\r?\n\s*)?(?P<name>[a-z][a-z\s'\-]*[a-z])", re.I),
]

FACILITIES = [
    "Ed Sackfield",
    "Elgin West",
    "Bayview Hill",
    "Richmond Green",
    "Oak Ridges",
]

_DATE_SEP = r"(?:-|to|–|—)"
_DATE_YEAR = r"(?:,\s*(\d{4}))?"
DATE_RANGE_PAT = re.compile(
    rf"(?:from\s+)?([a-z]{{3,9}})\s+(\d{{1,2}}){_DATE_YEAR}\s*{_DATE_SEP}\s*([a-z]{{3,9}})\s+(\d{{1,2}}){_DATE_YEAR}",
    re.I,
)


@dataclass(frozen=True)
class MetaParserConfig:
    """Configuration for metadata parsing from class schedule text."""

    facilities: Sequence[str] = ()
    date_range_pat: re.Pattern[str] = DATE_RANGE_PAT
    class_pat: re.Pattern[str] = CLASS_PAT
    loc_label_pat: re.Pattern[str] = LOC_LABEL_PAT
    default_year: int | None = None

    def __post_init__(self):
        """Set default facilities if not provided."""
        if not self.facilities:
            object.__setattr__(self, "facilities", FACILITIES)


def norm_time(hour: str, minute: str | None, ampm: str | None) -> str:
    """Normalize a matched clock time to 24-hour "HH:MM".

    Performs no range validation: callers that parse free-form email prose
    should use :func:`parse_clock_time`, which rejects non-times outright.
    """
    hh, mm = _to_24h_parts(hour, minute, ampm)
    return f"{hh:02d}:{mm:02d}"


def _to_24h_parts(hour: str, minute: str | None, ampm: str | None) -> tuple[int, int]:
    """Convert raw hour/minute/meridiem captures into 24-hour integer parts."""
    hh = int(hour)
    mm = int(minute or 0)
    a = (ampm or "").replace(".", "").lower()
    if a == "pm" and hh < 12:
        hh += 12
    if a == "am" and hh == 12:
        hh = 0
    return hh, mm


def parse_clock_time(hour: str, minute: str | None, ampm: str | None) -> str | None:
    """Normalize a clock time, returning None when the capture is not a time.

    ``RANGE_PAT`` runs against free-form prose, so it happily matches digits
    that are not clock values at all — a date ("Aug. 18"), a phone number, or
    the digits inside a class name such as "Glider2-3". Those produce hours
    above 23 or minutes above 59, which are rejected here so the caller can
    drop the event rather than emit a nonsense time like "80:00".
    """
    try:
        hh, mm = _to_24h_parts(hour, minute, ampm)
    except (TypeError, ValueError):
        return None
    if not (0 <= hh <= MAX_HOUR and 0 <= mm <= MAX_MINUTE):
        return None
    return f"{hh:02d}:{mm:02d}"


def is_plausible_session(start_time: str, end_time: str) -> bool:
    """Check that a start/end pair describes a real single class session.

    Rejects end-before-start (and zero-length) pairs, plus sessions longer than
    :data:`MAX_SESSION_MINUTES`. Both shapes come from RANGE_PAT pairing two
    unrelated times found in prose.
    """
    start = _minutes_since_midnight(start_time)
    end = _minutes_since_midnight(end_time)
    if start is None or end is None:
        return False
    duration = end - start
    return 0 < duration <= MAX_SESSION_MINUTES


def _minutes_since_midnight(value: str) -> int | None:
    """Parse "HH:MM" into minutes past midnight, or None if malformed."""
    try:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except (AttributeError, TypeError, ValueError):
        return None


def is_enrollment_notice(text: str | None) -> bool:
    """Check whether a body is a per-registrant enrollment/transfer notice.

    Both providers send far more than enrollment confirmations: marketing
    announcements ("we have opened a few additional class time slots"),
    monthly newsletters, payment receipts, and per-child skills reports. Every
    one of those carries day/time text that RANGE_PAT will match, so scanning
    on times alone turns a newsletter into a fabricated weekly class.

    Rather than blocklisting each genre, require the positive structure that
    only a real enrollment has: a named registrant tied to a schedule. WD Swim
    pairs "Student:" with a "Schedule:"/"New Time:"/"Old Time:" label, and
    Active RH pairs "[Pending] enrollment in <activity>" with "Meeting Dates:
    From". Broadcasts address "Dear Parents"/"Dear Vanesa" and name no
    registrant, so they fail both tests.
    """
    safe_text = text or ""
    has_student_schedule = bool(
        STUDENT_LABEL_PAT.search(safe_text) and SCHEDULE_LABEL_PAT.search(safe_text)
    )
    has_enrollment_dates = bool(
        ACTIVITY_ENROLLMENT_PAT.search(safe_text) and MEETING_DATES_PAT.search(safe_text)
    )
    return has_student_schedule or has_enrollment_dates


def extract_child(text: str | None) -> str | None:
    """Extract the registrant/child name from a class-schedule email body.

    Handles both observed providers: ``Student: <name>`` (WD Swim) and the name
    preceding ``[Pending] enrollment in`` (Active RH, in both its "Order
    Summary:" and processed-transaction phrasings). Casing is normalized so the
    same child is not reported under several spellings. Returns None when no
    name is found so callers can omit the key entirely.
    """
    safe_text = text or ""
    for pat in CHILD_PAT_PARTS:
        match = pat.search(safe_text)
        if not match:
            continue
        name = _clean_registrant_name(match.group("name"))
        if name:
            return name
    return None


def _clean_registrant_name(raw: str | None) -> str | None:
    """Normalize a captured registrant name, or None if it is really prose.

    The Active RH pattern is not anchored on a fixed label, so a capture can
    pick up preceding sentence text ("...has been processed. bennet sherwin",
    or in a newsletter, "...families have found"). Trim to the trailing words
    after any sentence boundary, then require every word to look like part of a
    personal name.

    Casing cannot make this distinction on its own: the real names arrive
    lowercase from the vendor ("bennet sherwin") while the prose is
    sentence-case ("Have Found"), so a capitalization test would invert the
    correct answer. Screening against a function-word list separates them.
    """
    collapsed = " ".join((raw or "").split())
    if not collapsed:
        return None
    # A sentence boundary inside the capture means everything before it is
    # preamble, not name.
    tail = collapsed.rsplit(".", 1)[-1].strip()
    words = tail.split()[-MAX_NAME_WORDS:]
    if not words or not all(_is_name_word(word) for word in words):
        return None
    return " ".join(words).title()


def _is_name_word(word: str) -> bool:
    """Check that a single token can plausibly be part of a personal name."""
    cleaned = word.strip("'-")
    if len(cleaned) < MIN_NAME_WORD_LEN:
        return False
    if cleaned.lower() in NON_NAME_WORDS:
        return False
    return cleaned.replace("'", "").replace("-", "").isalpha()


def extract_activity(text: str | None) -> str | None:
    """Extract the real activity/class name from a class-schedule email body.

    Derives the name from the email's own structure rather than a fixed list of
    known activities: ``Enrollment in <activity>`` for Active RH receipts and
    ``Class: <name>`` for WD Swim notices. Returns None when neither form is
    present, letting the caller fall back to a generic subject.
    """
    safe_text = text or ""
    for pat in (ACTIVITY_ENROLLMENT_PAT, ACTIVITY_CLASS_LABEL_PAT):
        match = pat.search(safe_text)
        if not match:
            continue
        activity = " ".join((match.group("activity") or "").split())
        if activity:
            return activity
    return None


def _infer_subject(text: str, cfg: "MetaParserConfig") -> str | None:
    """Derive the event subject, preferring a structurally-extracted activity."""
    activity = extract_activity(text)
    if activity:
        return activity
    class_match = cfg.class_pat.search(text)
    if class_match:
        return class_match.group(0).strip().title()
    return None


def _infer_location(text: str, cfg: "MetaParserConfig") -> str | None:
    """Extract location from text using label pattern or facility list."""
    loc_match = cfg.loc_label_pat.search(text)
    if loc_match:
        return loc_match.group(2).strip()
    for facility in cfg.facilities:
        if facility.lower() in text.lower():
            return facility
    return None


def _infer_date_range(text: str, cfg: "MetaParserConfig") -> dict[str, str] | None:
    """Extract date range from text. Returns dict or None."""
    date_match = cfg.date_range_pat.search(text)
    if not date_match:
        return None
    m1, d1, y1, m2, d2, y2 = date_match.groups()
    try:
        cur_year = cfg.default_year or 0
        y1f = int(y1 or y2 or cur_year)
        y2f = int(y2 or y1 or cur_year)
        start_date = f"{y1f:04d}-{MONTH_MAP[m1.lower()]:02d}-{int(d1):02d}"
        end_date = f"{y2f:04d}-{MONTH_MAP[m2.lower()]:02d}-{int(d2):02d}"
        return {"start_date": start_date, "until": end_date}
    except Exception:  # nosec B110 - non-critical metadata extraction
        return None


def infer_meta_from_text(
    text: str | None,
    config: "MetaParserConfig | None" = None,
) -> dict[str, Any]:
    """Extract metadata from class schedule text.

    Args:
        text: Input text to parse
        config: Optional parser configuration (uses defaults if None)

    Returns:
        Dictionary with extracted metadata (location, range, subject, child).
        Keys are omitted entirely when the corresponding value is not found.
    """
    cfg = config or MetaParserConfig()
    safe_text = text or ""
    meta: dict[str, Any] = {}

    loc = _infer_location(safe_text, cfg)
    if loc:
        meta["location"] = loc

    date_range = _infer_date_range(safe_text, cfg)
    if date_range:
        meta["range"] = date_range

    subject = _infer_subject(safe_text, cfg)
    if subject:
        meta["subject"] = subject

    child = extract_child(safe_text)
    if child:
        meta["child"] = child

    return meta
