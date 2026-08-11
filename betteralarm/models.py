"""The Alarm data model and its JSON-native (de)serialization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, time as dtime

from .timeparse import _DAY_NAMES, format_clock


def new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Alarm:
    id: str
    label: str
    type: str  # "once" | "repeat"
    enabled: bool = True
    at: datetime | None = None  # once: the concrete ring time
    time: dtime | None = None  # repeat: wall-clock time of day
    days: tuple[int, ...] = ()  # repeat: ISO weekdays, 0=Mon
    sound: str = "default"
    snooze_minutes: int | None = None
    snooze_until: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_dismissed: datetime | None = None
    open_url: str | None = None  # opened in the browser when this alarm fires
    skip_until: datetime | None = None  # repeat: suppress occurrences up to here
    interval_seconds: int | None = None  # interval: ring every N seconds

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "enabled": self.enabled,
            "at": self.at.isoformat() if self.at else None,
            "time": self.time.strftime("%H:%M") if self.time else None,
            "days": list(self.days),
            "sound": self.sound,
            "snooze_minutes": self.snooze_minutes,
            "snooze_until": self.snooze_until.isoformat() if self.snooze_until else None,
            "created_at": self.created_at.isoformat(),
            "last_dismissed": self.last_dismissed.isoformat() if self.last_dismissed else None,
            "open_url": self.open_url,
            "skip_until": self.skip_until.isoformat() if self.skip_until else None,
            "interval_seconds": self.interval_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Alarm":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in known}
        for key in ("at", "snooze_until", "created_at", "last_dismissed", "skip_until"):
            if kwargs.get(key):
                kwargs[key] = datetime.fromisoformat(kwargs[key])
        if kwargs.get("time"):
            h, m = kwargs["time"].split(":")
            kwargs["time"] = dtime(int(h), int(m))
        kwargs["days"] = tuple(kwargs.get("days") or ())
        kwargs.setdefault("label", "")
        alarm = cls(**kwargs)
        # validate shape now so a hand-edited file fails at load (where the store
        # skips bad entries with a warning) instead of crashing `alarm list` later
        if alarm.type == "once":
            if alarm.at is None:
                raise ValueError("once-alarm needs 'at'")
        elif alarm.type == "repeat":
            if alarm.time is None or not alarm.days:
                raise ValueError("repeat-alarm needs 'time' and 'days'")
        elif alarm.type == "interval":
            if not alarm.interval_seconds or alarm.interval_seconds < 1:
                raise ValueError("interval-alarm needs a positive 'interval_seconds'")
        else:
            raise ValueError(f"unknown alarm type {alarm.type!r}")
        return alarm

    def describe_schedule(self, time_format: str) -> str:
        """Human schedule summary: 'daily 07:30', 'mon,wed 08:00', 'Aug 11 16:05'."""
        if self.type == "once":
            if self.at is None:  # unreachable for loaded data (from_dict validates)
                return "?"
            # %-d is POSIX-only; build day-of-month portably
            return f"{self.at.strftime('%b')} {self.at.day} {format_clock(self.at, time_format, seconds=False)}"
        if self.type == "interval":
            from .timeparse import format_delta
            from datetime import timedelta

            return f"every {format_delta(timedelta(seconds=self.interval_seconds or 0))}"
        if self.time is None:
            return "?"
        clock = format_clock(
            datetime(2000, 1, 1, self.time.hour, self.time.minute), time_format, seconds=False
        )
        days = set(self.days)
        if days == set(range(7)):
            name = "daily"
        elif days == {0, 1, 2, 3, 4}:
            name = "weekdays"
        elif days == {5, 6}:
            name = "weekends"
        else:
            name = ",".join(_DAY_NAMES[d] for d in sorted(days))
        return f"{name} {clock}"
