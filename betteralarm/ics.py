"""Minimal .ics (iCalendar) reading: just enough to turn events into alarms.

Handles line unfolding, SUMMARY unescaping, and DTSTART in the three common
shapes (floating local, UTC 'Z', TZID=zone). All-day events are skipped —
an alarm needs a time of day.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_dtstart(value: str, params: list[str]) -> datetime | None:
    if any(p.upper().startswith("VALUE=DATE") for p in params) or "T" not in value:
        return None  # all-day event: no time of day to ring at
    is_utc = value.endswith("Z")
    tzid = next((p[5:] for p in params if p.upper().startswith("TZID=")), None)
    try:
        dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if is_utc:
        dt = dt.replace(tzinfo=timezone.utc)
    elif tzid:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            return dt  # unknown zone: take the wall time as local
    else:
        return dt  # floating time is local by definition
    return dt.astimezone().replace(tzinfo=None)


def parse_ics(text: str, now: datetime) -> list[tuple[str, datetime]]:
    """(summary, local datetime) for every future, timed VEVENT."""
    events: list[tuple[str, datetime]] = []
    in_event = False
    summary: str | None = None
    start: datetime | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            in_event, summary, start = True, None, None
        elif line == "END:VEVENT":
            if in_event and summary and start and start > now:
                events.append((summary, start))
            in_event = False
        elif in_event:
            name, sep, value = line.partition(":")
            if not sep:
                continue
            prop, *params = name.split(";")
            if prop.upper() == "SUMMARY":
                summary = _unescape(value.strip())
            elif prop.upper() == "DTSTART":
                start = _parse_dtstart(value.strip(), params)
    return events
