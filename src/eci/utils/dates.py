"""Date parsing and age-calculation utilities. Pure functions, UTC-aware throughout.

Lesson learned on a sibling project (Lucid Bot auditor): timestamp bugs from implicit
timezones are a recurring, expensive class of bug. Every function here is explicit about
UTC and never relies on naive datetime comparisons.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Union

DateLike = Union[str, datetime, date, None]

_KNOWN_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%b %d, %Y",  # Meta Ad Library (English UI): "Jul 6, 2026"
    "%B %d, %Y",  # "July 6, 2026"
)

# Meta Ad Library renders dates as "6 jul 2026" / "16 may 2026" when browsed in Spanish
# (the exact wording the eci.sources.meta_web_scraper scraper observes). Python's strptime
# needs the OS locale set to Spanish to parse "%d %b %Y" with these abbreviations, which we
# can't rely on in a deployment environment — so this is a small, explicit lookup instead.
_SPANISH_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
}
_SPANISH_DATE_RE = re.compile(
    r"(\d{1,2})\s+de\s+([a-zA-Zé]+)\s+de\s+(\d{4})|(\d{1,2})\s+([a-zA-Zé]{3,4})\.?\s+(\d{4})"
)


def parse_spanish_date(text: str | None) -> datetime | None:
    """Parses Meta Ad Library's Spanish date rendering: '6 jul 2026' or '16 de julio de
    2026'. Returns None (not today, not a guess) when the text doesn't match — callers
    should treat that as `not_available`."""
    if not text:
        return None
    match = _SPANISH_DATE_RE.search(text.strip().lower())
    if not match:
        return None
    if match.group(1):
        day, month_name, year = match.group(1), match.group(2), match.group(3)
    else:
        day, month_name, year = match.group(4), match.group(5), match.group(6)
    month = _SPANISH_MONTHS.get(month_name[:3].rstrip("."))
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_date(value: DateLike) -> datetime | None:
    """Best-effort parse into a UTC-aware datetime. Returns None (never raises) on failure —
    callers must treat that as `not_available`, never assume "today"."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    for fmt in _KNOWN_FORMATS:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # Meta Ad Library's Spanish UI ("6 jul 2026") — see parse_spanish_date's docstring.
    spanish = parse_spanish_date(text)
    if spanish is not None:
        return spanish

    return None


def age_days(start: DateLike, *, as_of: datetime | None = None) -> int | None:
    """Whole days between `start` and `as_of` (default: now, UTC). None if unparseable."""
    started = parse_date(start)
    if started is None:
        return None
    reference = as_of or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta = reference - started
    return max(delta.days, 0)


def in_reference_window(
    start: DateLike,
    *,
    min_age_days: int = 30,
    max_age_days: int = 90,
    as_of: datetime | None = None,
) -> bool | None:
    """True if the ad's age falls inside [min_age_days, max_age_days] — the persistence
    reference window requested by the operator. None (not False) when age is unknown, so
    callers don't silently misclassify missing data as "outside the window"."""
    age = age_days(start, as_of=as_of)
    if age is None:
        return None
    return min_age_days <= age <= max_age_days
