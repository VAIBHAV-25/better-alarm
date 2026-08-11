"""Pure next-occurrence math. Everything takes `now` explicitly — no clocks in here."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from .models import Alarm

GRACE = timedelta(minutes=5)


def next_ring(alarm: Alarm, now: datetime) -> datetime | None:
    """When this alarm rings next, or None if it never will.

    Strictly after `now`: an occurrence at exactly `now` was either just fired
    (the engine caches targets) or just dismissed — either way it must not reappear.
    """
    if not alarm.enabled:
        return None
    if alarm.snooze_until and alarm.snooze_until > now:
        return alarm.snooze_until
    # `alarm skip` suppresses occurrences up to skip_until
    floor = alarm.skip_until if alarm.skip_until and alarm.skip_until > now else now
    if alarm.type == "once":
        return alarm.at if alarm.at and alarm.at > floor else None
    if alarm.type == "interval":
        if not alarm.interval_seconds:
            return None
        base = alarm.last_dismissed or alarm.created_at
        step = timedelta(seconds=alarm.interval_seconds)
        ring = base + step
        if ring <= floor:
            ring = base + (int((floor - base) / step) + 1) * step
            while ring <= floor:  # guard against integer-division edge cases
                ring += step
        return ring
    if alarm.time is None or not alarm.days:
        return None
    for offset in range(9):
        candidate = datetime.combine(floor.date() + timedelta(days=offset), alarm.time)
        if candidate > floor and candidate.weekday() in alarm.days:
            return candidate
    return None


def next_alarm(alarms: Iterable[Alarm], now: datetime) -> tuple[Alarm, datetime] | None:
    """The soonest-ringing alarm and its ring time, or None."""
    best: tuple[Alarm, datetime] | None = None
    for alarm in alarms:
        ring = next_ring(alarm, now)
        if ring is not None and (best is None or ring < best[1]):
            best = (alarm, ring)
    return best


def missed(alarms: Iterable[Alarm], now: datetime, grace: timedelta = GRACE) -> list[Alarm]:
    """Enabled one-shot alarms whose effective due time passed more than `grace` ago.

    An active snooze supersedes the original time in both directions: a future
    snooze means not missed, and a snooze that lapsed within grace is a due ring
    (last_due picks it up), not a missed one.
    """
    out = []
    for a in alarms:
        if a.type != "once" or not a.enabled or a.at is None:
            continue
        if a.snooze_until and a.snooze_until > now:
            continue
        due = a.snooze_until or a.at
        if due < now - grace:
            out.append(a)
    return out


def last_due(alarm: Alarm, now: datetime, grace: timedelta = GRACE) -> datetime | None:
    """The most recent occurrence within the grace window that still deserves a ring.

    Used at startup: 'the clock was off for a moment, did we just miss something?'
    Covers expired snoozes, once-alarms, and today's/yesterday's repeat occurrence
    (unless it was already dismissed).
    """
    if not alarm.enabled:
        return None
    if alarm.snooze_until:
        if alarm.snooze_until > now:
            return None  # still snoozing; next_ring handles it
        return alarm.snooze_until if now - grace <= alarm.snooze_until else None
    if alarm.type == "once":
        if alarm.at is not None and now - grace <= alarm.at <= now:
            return alarm.at
        return None
    if alarm.time is None or not alarm.days:
        return None
    for offset in (0, 1):  # today, then yesterday (grace can straddle midnight)
        candidate = datetime.combine(now.date() - timedelta(days=offset), alarm.time)
        if candidate.weekday() not in alarm.days:
            continue
        if alarm.skip_until and candidate <= alarm.skip_until:
            continue  # this occurrence was explicitly skipped
        if now - grace <= candidate <= now:
            if alarm.last_dismissed and alarm.last_dismissed >= candidate:
                return None
            return candidate
    return None
