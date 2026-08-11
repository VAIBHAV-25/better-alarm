from datetime import datetime, time, timedelta

from betteralarm.config import Config
from betteralarm.engine import Dirty, Dismissed, Engine, Fired, Missed, Phase, Snoozed
from betteralarm.models import Alarm
from betteralarm.store import AppState

T0 = datetime(2026, 8, 11, 7, 29, 0)  # Tuesday
T_FIRE = datetime(2026, 8, 11, 7, 30, 0)


def once(**kw):
    defaults = dict(id="o1", label="tea", type="once", at=T_FIRE)
    return Alarm(**(defaults | kw))


def repeat(**kw):
    defaults = dict(id="r1", label="wake", type="repeat", time=time(7, 30), days=tuple(range(7)))
    return Alarm(**(defaults | kw))


def engine_with(*alarms, **config_kw):
    state = AppState(config=Config(**config_kw), alarms=list(alarms))
    engine = Engine(state)
    engine.start(T0)
    return engine


def events_of(events, kind):
    return [e for e in events if isinstance(e, kind)]


class TestFiring:
    def test_idle_before_target(self):
        engine = engine_with(once())
        assert engine.tick(T0 + timedelta(seconds=30)) == []
        assert engine.phase is Phase.IDLE

    def test_fires_at_target(self):
        engine = engine_with(once())
        events = engine.tick(T_FIRE)
        assert [type(e) for e in events] == [Fired]
        assert engine.phase is Phase.RINGING
        assert engine.session.alarm_id == "o1"

    def test_fires_shortly_after_target(self):
        engine = engine_with(once())
        events = engine.tick(T_FIRE + timedelta(seconds=0.4))
        assert events_of(events, Fired)

    def test_no_refire_while_ringing(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        assert engine.tick(T_FIRE + timedelta(seconds=1)) == []

    def test_disabled_never_fires(self):
        engine = engine_with(once(enabled=False))
        assert engine.tick(T_FIRE) == []

    def test_two_due_ring_fifo(self):
        first = once(id="a", at=T_FIRE)
        second = once(id="b", at=T_FIRE + timedelta(seconds=10))
        engine = engine_with(first, second)
        late = T_FIRE + timedelta(minutes=1)
        events = engine.tick(late)
        assert events_of(events, Fired)[0].alarm.id == "a"
        engine.handle_key("d", late)
        events = engine.tick(late)
        assert events_of(events, Fired)[0].alarm.id == "b"


class TestDismiss:
    def test_dismiss_once_disables_it(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        events = engine.handle_key("d", T_FIRE + timedelta(seconds=5))
        assert events_of(events, Dismissed) and events_of(events, Dirty)
        assert engine.phase is Phase.IDLE
        alarm = engine.state.alarms[0]
        assert alarm.enabled is False
        assert alarm.last_dismissed is not None

    def test_enter_dismisses(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        assert events_of(engine.handle_key("enter", T_FIRE), Dismissed)

    def test_dismiss_repeat_schedules_tomorrow(self):
        engine = engine_with(repeat())
        engine.tick(T_FIRE)
        engine.handle_key("d", T_FIRE + timedelta(seconds=5))
        alarm = engine.state.alarms[0]
        assert alarm.enabled is True
        assert engine.targets["r1"] == datetime(2026, 8, 12, 7, 30)

    def test_keys_ignored_when_idle(self):
        engine = engine_with(once())
        assert engine.handle_key("d", T0) == []
        assert engine.handle_key("s", T0) == []


class TestSnooze:
    def test_snooze_sets_until_and_returns_to_idle(self):
        engine = engine_with(once())  # default snooze 5m
        engine.tick(T_FIRE)
        events = engine.handle_key("s", T_FIRE + timedelta(seconds=10))
        snoozed = events_of(events, Snoozed)[0]
        assert snoozed.until == T_FIRE + timedelta(seconds=10, minutes=5)
        assert engine.phase is Phase.IDLE
        assert engine.state.alarms[0].snooze_until == snoozed.until

    def test_per_alarm_snooze_duration_wins(self):
        engine = engine_with(once(snooze_minutes=2))
        engine.tick(T_FIRE)
        events = engine.handle_key("s", T_FIRE)
        assert events_of(events, Snoozed)[0].until == T_FIRE + timedelta(minutes=2)

    def test_hand_edited_zero_snooze_clamped_to_a_minute(self):
        engine = engine_with(once(snooze_minutes=0))  # only possible via hand-edited JSON
        engine.tick(T_FIRE)
        events = engine.handle_key("s", T_FIRE)
        assert events_of(events, Snoozed)[0].until >= T_FIRE + timedelta(minutes=1)

    def test_snoozed_alarm_refires(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        engine.handle_key("s", T_FIRE)
        wake = T_FIRE + timedelta(minutes=9)
        assert events_of(engine.tick(wake), Fired)

    def test_dismiss_after_snooze_clears_snooze(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        engine.handle_key("s", T_FIRE)
        engine.tick(T_FIRE + timedelta(minutes=9))
        engine.handle_key("d", T_FIRE + timedelta(minutes=9))
        assert engine.state.alarms[0].snooze_until is None


class TestAutoAction:
    def test_auto_snooze_when_unattended(self):
        engine = engine_with(once())  # auto_action snooze after 5m
        engine.tick(T_FIRE)
        events = engine.tick(T_FIRE + timedelta(minutes=5))
        snoozed = events_of(events, Snoozed)
        assert snoozed and snoozed[0].auto
        assert engine.phase is Phase.IDLE

    def test_auto_dismiss_after_max_auto_snoozes(self):
        engine = engine_with(once(), max_auto_snoozes=1, auto_action_minutes=5)
        engine.tick(T_FIRE)
        events = engine.tick(T_FIRE + timedelta(minutes=5))  # auto-snooze #1
        assert events_of(events, Snoozed)
        refire = T_FIRE + timedelta(minutes=5 + 9)
        engine.tick(refire)
        events = engine.tick(refire + timedelta(minutes=5))
        dismissed = events_of(events, Dismissed)
        assert dismissed and dismissed[0].auto
        assert engine.state.alarms[0].enabled is False

    def test_auto_dismiss_policy(self):
        engine = engine_with(once(), auto_action="dismiss")
        engine.tick(T_FIRE)
        events = engine.tick(T_FIRE + timedelta(minutes=5))
        assert events_of(events, Dismissed)

    def test_manual_snooze_not_counted_as_auto(self):
        engine = engine_with(once(), max_auto_snoozes=1)
        engine.tick(T_FIRE)
        engine.handle_key("s", T_FIRE)  # manual
        engine.tick(T_FIRE + timedelta(minutes=9))
        events = engine.tick(T_FIRE + timedelta(minutes=14))
        assert events_of(events, Snoozed)  # still allowed one auto


class TestStartup:
    def test_missed_swept_on_start(self):
        stale = once(at=T0 - timedelta(hours=2))
        state = AppState(config=Config(), alarms=[stale])
        engine = Engine(state)
        events = engine.start(T0)
        assert events_of(events, Missed)[0].alarms == [stale]
        assert events_of(events, Dirty)
        assert stale.enabled is False

    def test_due_within_grace_fires_on_start(self):
        recent = once(at=T0 - timedelta(minutes=2))
        state = AppState(config=Config(), alarms=[recent])
        engine = Engine(state)
        engine.start(T0)
        assert events_of(engine.tick(T0), Fired)

    def test_clean_start_no_events(self):
        assert engine_with(once()).phase is Phase.IDLE

    def test_repeat_due_within_grace_fires_on_start(self):
        # daily 7:27 alarm, `run` launched 7:29 — today's ring is 2 min late, not skipped
        state = AppState(config=Config(), alarms=[repeat(time=time(7, 27))])
        engine = Engine(state)
        engine.start(T0)
        assert events_of(engine.tick(T0), Fired)

    def test_repeat_dismissed_today_not_refired_on_start(self):
        alarm = repeat(time=time(7, 27), last_dismissed=T0 - timedelta(minutes=1))
        state = AppState(config=Config(), alarms=[alarm])
        engine = Engine(state)
        engine.start(T0)
        assert engine.tick(T0) == []

    def test_expired_snooze_within_grace_fires_on_start(self):
        alarm = once(at=T0 - timedelta(hours=1), snooze_until=T0 - timedelta(minutes=1))
        state = AppState(config=Config(), alarms=[alarm])
        engine = Engine(state)
        events = engine.start(T0)
        assert not events_of(events, Missed)
        assert events_of(engine.tick(T0), Fired)


class TestRecompute:
    def test_reload_picks_up_new_alarm(self):
        engine = engine_with(once())
        engine.state.alarms.append(once(id="o2", at=T0 + timedelta(minutes=5)))
        engine.recompute(T0)
        assert "o2" in engine.targets


class TestDigitSnooze:
    def test_digit_snoozes_that_many_minutes(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        events = engine.handle_key("3", T_FIRE + timedelta(seconds=5))
        snoozed = events_of(events, Snoozed)[0]
        assert snoozed.until == T_FIRE + timedelta(seconds=5, minutes=3)
        assert engine.phase is Phase.IDLE

    def test_zero_is_ignored(self):
        engine = engine_with(once())
        engine.tick(T_FIRE)
        assert engine.handle_key("0", T_FIRE) == []
        assert engine.phase is Phase.RINGING
