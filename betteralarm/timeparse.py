"""Parsing and formatting of times, day lists, and durations."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

TIME_FORMATS_HELP = (
    "accepted formats: 7:30, 07:30, 0730, 730, 7, 7am, 7:30pm, 12am (midnight), 12pm (noon)"
)

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_ALIASES = {
    "daily": (0, 1, 2, 3, 4, 5, 6),
    "weekdays": (0, 1, 2, 3, 4),
    "weekends": (5, 6),
    "once": (),
}

_TIME_RE = re.compile(
    r"^(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?(?P<ampm>am|pm)?$", re.IGNORECASE
)
_DURATION_RE = re.compile(
    r"^(?:(?P<hours>\d+(?:\.\d+)?)h)?\s*(?:(?P<minutes>\d+(?:\.\d+)?)m)?\s*(?:(?P<seconds>\d+(?:\.\d+)?)s)?$"
)


def parse_time(raw: str) -> time:
    """Parse a wall-clock time like '7:30', '0730', or '7:30pm'."""
    s = re.sub(r"\s+", "", raw.strip().lower())  # humans write "6:03 pm"
    m = _TIME_RE.match(s)
    hour = minute = None
    ampm = None
    if m:
        hour, minute = int(m.group("hour")), int(m.group("minute") or 0)
        ampm = m.group("ampm")
    elif s.isdigit() and len(s) in (3, 4):  # "730" / "0730"
        hour, minute = int(s[:-2]), int(s[-2:])
    if hour is None:
        raise ValueError(f"can't parse time {raw!r}; {TIME_FORMATS_HELP}")
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError(f"hour must be 1-12 with am/pm, got {raw!r}")
        if ampm == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"can't parse time {raw!r}; {TIME_FORMATS_HELP}")
    return time(hour, minute)


_FULL_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

WHEN_FORMATS_HELP = "try 'tomorrow 9am', 'monday 7pm', or 'aug 20 14:00'"


def _weekday_index(word: str) -> int | None:
    if len(word) < 3:
        return None
    for i, name in enumerate(_FULL_DAY_NAMES):
        if name.startswith(word[:3]) and name.startswith(word) or word == name:
            return i
    return None


def parse_when(raw: str, now: datetime) -> datetime:
    """Parse a day+time phrase into the next matching datetime.

    Understands: 'today 23:15', 'tomorrow 9am', '<weekday> 7pm' (next
    occurrence), and '<month> <day> <time>' (this year, else next).
    """
    s = " ".join(raw.strip().lower().replace(" at ", " ").split())
    tokens = s.split()
    if not tokens:
        raise ValueError(f"can't parse {raw!r}; {WHEN_FORMATS_HELP}")
    head, rest = tokens[0], " ".join(tokens[1:])

    if head in ("today", "tomorrow"):
        if not rest:
            raise ValueError(f"need a time too, e.g. '{head} 9am'")
        when = datetime.combine(
            now.date() + timedelta(days=1 if head == "tomorrow" else 0), parse_time(rest)
        )
        if when <= now:
            raise ValueError(f"{raw!r} already passed — did you mean tomorrow?")
        return when

    weekday = _weekday_index(head)
    if weekday is not None:
        if not rest:
            raise ValueError(f"need a time too, e.g. '{head} 7pm'")
        t = parse_time(rest)
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            candidate = datetime.combine(day, t)
            if day.weekday() == weekday and candidate > now:
                return candidate
        raise ValueError(f"can't schedule {raw!r}")  # unreachable

    if head[:3] in _MONTH_NAMES and len(tokens) >= 3 and tokens[1].isdigit():
        month = _MONTH_NAMES.index(head[:3]) + 1
        day_of_month = int(tokens[1])
        t = parse_time(" ".join(tokens[2:]))
        try:
            when = datetime(now.year, month, day_of_month, t.hour, t.minute)
        except ValueError as exc:
            raise ValueError(f"can't parse {raw!r}: {exc}") from None
        if when <= now:
            when = when.replace(year=now.year + 1)
        return when

    raise ValueError(f"can't parse {raw!r}; {WHEN_FORMATS_HELP}")


def parse_days(raw: str) -> tuple[int, ...]:
    """Parse a repeat spec into a sorted tuple of ISO weekdays (0=Mon)."""
    s = raw.strip().lower()
    if s in _DAY_ALIASES:
        return _DAY_ALIASES[s]
    if not s:
        raise ValueError("empty repeat spec")
    days = set()
    for part in s.split(","):
        part = part.strip()
        matches = [i for i, name in enumerate(_DAY_NAMES) if part[:3] == name]
        if len(part) < 3 or not matches:
            raise ValueError(
                f"unknown day {part!r}; use once, daily, weekdays, weekends, "
                "or day names like mon,wed,fri"
            )
        days.add(matches[0])
    return tuple(sorted(days))


def parse_duration(raw: str) -> timedelta:
    """Parse a duration like '25m', '1h30m', '90s'; a bare number means minutes."""
    s = raw.strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        td = timedelta(minutes=float(s))
    else:
        m = _DURATION_RE.match(s)
        if not m or not any(m.groupdict().values()):
            raise ValueError(
                f"can't parse duration {raw!r}; try 25m, 1h30m, 90s, or a bare number of minutes"
            )
        td = timedelta(
            hours=float(m.group("hours") or 0),
            minutes=float(m.group("minutes") or 0),
            seconds=float(m.group("seconds") or 0),
        )
    if td <= timedelta(0):
        raise ValueError("duration must be positive")
    return td


def format_delta(td: timedelta) -> str:
    """Humanize a timedelta: '15h 41m', '3m 20s', '2d 3h', 'now'."""
    total = int(td.total_seconds())
    if total <= 0:
        return "now"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes >= 10 or (minutes and not seconds):
        return f"{minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_clock(dt: datetime, time_format: str, seconds: bool = True) -> str:
    """Format a datetime's time per config ('24' or '12')."""
    if time_format == "12":
        fmt = "%I:%M:%S %p" if seconds else "%I:%M %p"
        return dt.strftime(fmt).lstrip("0")
    return dt.strftime("%H:%M:%S" if seconds else "%H:%M")
