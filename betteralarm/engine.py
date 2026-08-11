"""The ringing state machine. Pure: no I/O, no clocks — `now` always comes in.

The engine turns key presses and clock ticks into events; run.py maps events to
side effects (sound, saving). Fire targets are cached in `targets` so an
occurrence stays due until it is handled (a fresh next_ring at the fire instant
would already have skipped past it).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import Alarm
from .scheduler import GRACE, last_due, missed, next_ring
from .store import AppState


class Phase(enum.Enum):
    IDLE = "idle"
    RINGING = "ringing"


@dataclass(frozen=True)
class Fired:
    alarm: Alarm


@dataclass(frozen=True)
class Snoozed:
    alarm: Alarm
    until: datetime
    auto: bool = False


@dataclass(frozen=True)
class Dismissed:
    alarm: Alarm
    auto: bool = False


@dataclass(frozen=True)
class Missed:
    alarms: list[Alarm]


@dataclass(frozen=True)
class Dirty:
    """State changed; run.py should persist it."""


@dataclass
class RingSession:
    alarm_id: str
    target: datetime
    started_at: datetime


class Engine:
    def __init__(self, state: AppState, grace: timedelta = GRACE):
        self.state = state
        self.grace = grace
        self.phase = Phase.IDLE
        self.session: RingSession | None = None
        self.targets: dict[str, datetime] = {}
        self._auto_snoozes: dict[str, int] = {}  # per ring incident, cleared on dismiss

    # ------------------------------------------------------------- lifecycle

    def start(self, now: datetime) -> list:
        """Sweep missed alarms, compute targets, arm anything due within grace."""
        events: list = []
        stale = missed(self.state.alarms, now, self.grace)
        for alarm in stale:
            alarm.enabled = False
            alarm.last_dismissed = now
        if stale:
            events += [Missed(stale), Dirty()]
        self.recompute(now)
        for alarm in self.state.alarms:
            due = last_due(alarm, now, self.grace)
            if due is not None:
                self.targets[alarm.id] = due
        return events

    def recompute(self, now: datetime) -> None:
        """Rebuild the target cache, preserving occurrences that are still due."""
        old = self.targets
        self.targets = {}
        for alarm in self.state.alarms:
            pending = old.get(alarm.id)
            still_due = (
                pending is not None
                and pending <= now
                and alarm.enabled
                and not (alarm.snooze_until and alarm.snooze_until > now)
            )
            if still_due:
                self.targets[alarm.id] = pending
                continue
            ring = next_ring(alarm, now)
            if ring is not None:
                self.targets[alarm.id] = ring

    # ------------------------------------------------------------- the loop

    def tick(self, now: datetime) -> list:
        if self.phase is Phase.RINGING:
            return self._tick_ringing(now)
        due = [(target, aid) for aid, target in self.targets.items() if target <= now]
        if not due:
            return []
        target, alarm_id = min(due)
        del self.targets[alarm_id]
        alarm = self._alarm(alarm_id)
        self.phase = Phase.RINGING
        self.session = RingSession(alarm_id=alarm_id, target=target, started_at=now)
        return [Fired(alarm)]

    def _tick_ringing(self, now: datetime) -> list:
        cfg = self.state.config
        assert self.session is not None
        if now - self.session.started_at < timedelta(minutes=cfg.auto_action_minutes):
            return []
        exhausted = self._auto_snoozes.get(self.session.alarm_id, 0) >= cfg.max_auto_snoozes
        if cfg.auto_action == "dismiss" or exhausted:
            return self._dismiss(now, auto=True)
        return self._snooze(now, auto=True)

    def handle_key(self, key: str, now: datetime) -> list:
        if self.phase is not Phase.RINGING:
            return []
        if key == "s":
            return self._snooze(now)
        if key.isdigit() and key != "0":  # 1-9: snooze exactly that many minutes
            return self._snooze(now, minutes=int(key))
        if key in ("d", "enter"):
            return self._dismiss(now)
        return []

    # ------------------------------------------------------------- actions

    def _snooze(self, now: datetime, auto: bool = False, minutes: int | None = None) -> list:
        alarm = self._alarm(self.session.alarm_id)
        if minutes is None:
            minutes = alarm.snooze_minutes or self.state.config.snooze_minutes
        # minimum one minute: a 0/negative snooze (hand-edited file) would refire instantly
        alarm.snooze_until = now + timedelta(minutes=max(1, minutes))
        if auto:
            self._auto_snoozes[alarm.id] = self._auto_snoozes.get(alarm.id, 0) + 1
        self._end_session(now)
        return [Snoozed(alarm, alarm.snooze_until, auto=auto), Dirty()]

    def _dismiss(self, now: datetime, auto: bool = False) -> list:
        alarm = self._alarm(self.session.alarm_id)
        alarm.snooze_until = None
        alarm.last_dismissed = now
        if alarm.type == "once":
            alarm.enabled = False  # spent
        self._auto_snoozes.pop(alarm.id, None)
        self._end_session(now)
        return [Dismissed(alarm, auto=auto), Dirty()]

    def abort_ring(self, now: datetime) -> None:
        """The ring was handled elsewhere (another terminal, the fullscreen clock)."""
        if self.phase is Phase.RINGING:
            self._end_session(now)

    def _end_session(self, now: datetime) -> None:
        self.phase = Phase.IDLE
        self.session = None
        self.recompute(now)

    def _alarm(self, alarm_id: str) -> Alarm:
        return next(a for a in self.state.alarms if a.id == alarm_id)

    @property
    def ringing_alarm(self) -> Alarm | None:
        return self._alarm(self.session.alarm_id) if self.session else None
