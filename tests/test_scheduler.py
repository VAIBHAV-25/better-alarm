from datetime import datetime, time, timedelta

from betteralarm.models import Alarm
from betteralarm.scheduler import last_due, missed, next_alarm, next_ring

# Tue Aug 11 2026, 07:29 — weekday(1)
NOW = datetime(2026, 8, 11, 7, 29)


def once(**kw):
    defaults = dict(id="o1", label="tea", type="once", at=NOW + timedelta(hours=1))
    return Alarm(**(defaults | kw))


def repeat(**kw):
    defaults = dict(id="r1", label="wake", type="repeat", time=time(7, 30), days=tuple(range(7)))
    return Alarm(**(defaults | kw))


class TestNextRingOnce:
    def test_future(self):
        assert next_ring(once(), NOW) == NOW + timedelta(hours=1)

    def test_past_returns_none(self):
        assert next_ring(once(at=NOW - timedelta(minutes=1)), NOW) is None

    def test_exactly_now_returns_none(self):
        assert next_ring(once(at=NOW), NOW) is None

    def test_disabled(self):
        assert next_ring(once(enabled=False), NOW) is None


class TestNextRingRepeat:
    def test_later_today(self):
        assert next_ring(repeat(), NOW) == datetime(2026, 8, 11, 7, 30)

    def test_earlier_today_rolls_to_tomorrow(self):
        a = repeat(time=time(7, 0))
        assert next_ring(a, NOW) == datetime(2026, 8, 12, 7, 0)

    def test_weekdays_from_friday_night(self):
        friday_night = datetime(2026, 8, 14, 22, 0)  # Fri
        a = repeat(days=(0, 1, 2, 3, 4), time=time(9, 25))
        assert next_ring(a, friday_night) == datetime(2026, 8, 17, 9, 25)  # Mon

    def test_weekends(self):
        a = repeat(days=(5, 6), time=time(10, 0))
        assert next_ring(a, NOW) == datetime(2026, 8, 15, 10, 0)  # Sat

    def test_single_day_next_week(self):
        a = repeat(days=(1,), time=time(7, 0))  # Tuesdays, but 7:00 already passed
        assert next_ring(a, NOW) == datetime(2026, 8, 18, 7, 0)

    def test_occurrence_at_exactly_now_skipped(self):
        at_730 = datetime(2026, 8, 11, 7, 30)
        assert next_ring(repeat(), at_730) == datetime(2026, 8, 12, 7, 30)

    def test_day_boundary(self):
        a = repeat(time=time(23, 59))
        late = datetime(2026, 8, 11, 23, 59, 30)
        assert next_ring(a, late) == datetime(2026, 8, 12, 23, 59)

    def test_disabled(self):
        assert next_ring(repeat(enabled=False), NOW) is None


class TestSnoozePrecedence:
    def test_snooze_until_wins(self):
        a = repeat(snooze_until=NOW + timedelta(minutes=5))
        assert next_ring(a, NOW) == NOW + timedelta(minutes=5)

    def test_expired_snooze_ignored(self):
        a = repeat(snooze_until=NOW - timedelta(minutes=5))
        assert next_ring(a, NOW) == datetime(2026, 8, 11, 7, 30)

    def test_snoozed_once_alarm(self):
        a = once(at=NOW - timedelta(minutes=10), snooze_until=NOW + timedelta(minutes=2))
        assert next_ring(a, NOW) == NOW + timedelta(minutes=2)


class TestNextAlarm:
    def test_picks_soonest(self):
        soon = once(id="s", at=NOW + timedelta(minutes=10))
        later = once(id="l", at=NOW + timedelta(hours=2))
        assert next_alarm([later, soon], NOW) == (soon, NOW + timedelta(minutes=10))

    def test_skips_unschedulable(self):
        disabled = repeat(enabled=False)
        past = once(at=NOW - timedelta(days=1))
        assert next_alarm([disabled, past], NOW) is None

    def test_empty(self):
        assert next_alarm([], NOW) is None


class TestMissed:
    def test_once_past_grace_is_missed(self):
        a = once(at=NOW - timedelta(minutes=6))
        assert missed([a], NOW) == [a]

    def test_within_grace_not_missed(self):
        a = once(at=NOW - timedelta(minutes=4))
        assert missed([a], NOW) == []

    def test_disabled_not_missed(self):
        a = once(at=NOW - timedelta(hours=1), enabled=False)
        assert missed([a], NOW) == []

    def test_repeat_never_missed(self):
        assert missed([repeat()], NOW) == []

    def test_snoozed_not_missed(self):
        a = once(at=NOW - timedelta(hours=1), snooze_until=NOW + timedelta(minutes=1))
        assert missed([a], NOW) == []

    def test_snooze_expired_within_grace_not_missed(self):
        # rang at 6:29, snoozed to 7:28, app killed, restarted 7:29 — the snooze
        # lapsed 1 minute ago: that's a due ring, not a missed alarm
        a = once(at=NOW - timedelta(hours=1), snooze_until=NOW - timedelta(minutes=1))
        assert missed([a], NOW) == []

    def test_snooze_expired_beyond_grace_missed(self):
        a = once(at=NOW - timedelta(hours=1), snooze_until=NOW - timedelta(minutes=10))
        assert missed([a], NOW) == [a]


class TestLastDue:
    def test_once_within_grace(self):
        a = once(at=NOW - timedelta(minutes=2))
        assert last_due(a, NOW) == NOW - timedelta(minutes=2)

    def test_once_beyond_grace(self):
        assert last_due(once(at=NOW - timedelta(minutes=6)), NOW) is None

    def test_once_future(self):
        assert last_due(once(), NOW) is None

    def test_disabled(self):
        assert last_due(once(at=NOW - timedelta(minutes=2), enabled=False), NOW) is None

    def test_repeat_occurrence_within_grace(self):
        a = repeat(time=time(7, 27))  # daily, 2 minutes ago
        assert last_due(a, NOW) == datetime(2026, 8, 11, 7, 27)

    def test_repeat_occurrence_beyond_grace(self):
        assert last_due(repeat(time=time(7, 0)), NOW) is None

    def test_repeat_wrong_day(self):
        a = repeat(time=time(7, 27), days=(0,))  # Mondays only; NOW is Tuesday
        assert last_due(a, NOW) is None

    def test_repeat_already_dismissed(self):
        a = repeat(time=time(7, 27), last_dismissed=NOW - timedelta(minutes=1))
        assert last_due(a, NOW) is None

    def test_repeat_midnight_boundary(self):
        a = repeat(time=time(23, 58))
        just_after_midnight = datetime(2026, 8, 12, 0, 1)
        assert last_due(a, just_after_midnight) == datetime(2026, 8, 11, 23, 58)

    def test_expired_snooze_within_grace(self):
        a = once(at=NOW - timedelta(hours=1), snooze_until=NOW - timedelta(minutes=1))
        assert last_due(a, NOW) == NOW - timedelta(minutes=1)

    def test_future_snooze_is_not_due(self):
        a = once(at=NOW - timedelta(hours=1), snooze_until=NOW + timedelta(minutes=3))
        assert last_due(a, NOW) is None


class TestSkipUntil:
    def test_repeat_skips_occurrences_up_to_skip_until(self):
        from betteralarm.scheduler import next_ring
        from betteralarm.models import Alarm
        from datetime import datetime, time, timedelta

        now = datetime(2026, 8, 11, 17, 0)  # Tuesday
        a = Alarm(id="x", label="", type="repeat", time=time(9, 0), days=tuple(range(7)))
        a.skip_until = datetime(2026, 8, 12, 9, 0)  # skip Wednesday's ring
        assert next_ring(a, now) == datetime(2026, 8, 13, 9, 0)

    def test_lapsed_skip_is_inert(self):
        from betteralarm.scheduler import next_ring
        from betteralarm.models import Alarm
        from datetime import datetime, time

        now = datetime(2026, 8, 11, 17, 0)
        a = Alarm(id="x", label="", type="repeat", time=time(9, 0), days=tuple(range(7)))
        a.skip_until = datetime(2026, 8, 1, 9, 0)  # long past
        assert next_ring(a, now) == datetime(2026, 8, 12, 9, 0)


class TestIntervalAlarms:
    def _interval(self, seconds=1800, **kw):
        from betteralarm.models import Alarm
        from datetime import datetime

        return Alarm(
            id="i1", label="water", type="interval", interval_seconds=seconds,
            created_at=datetime(2026, 8, 11, 12, 0), **kw,
        )

    def test_first_ring_is_one_interval_after_creation(self):
        from betteralarm.scheduler import next_ring
        from datetime import datetime

        a = self._interval()
        assert next_ring(a, datetime(2026, 8, 11, 12, 0)) == datetime(2026, 8, 11, 12, 30)

    def test_rings_advance_on_the_grid(self):
        from betteralarm.scheduler import next_ring
        from datetime import datetime

        a = self._interval()
        assert next_ring(a, datetime(2026, 8, 11, 13, 10)) == datetime(2026, 8, 11, 13, 30)

    def test_dismissal_re_anchors(self):
        from betteralarm.scheduler import next_ring
        from datetime import datetime

        a = self._interval()
        a.last_dismissed = datetime(2026, 8, 11, 13, 7)
        assert next_ring(a, datetime(2026, 8, 11, 13, 8)) == datetime(2026, 8, 11, 13, 37)
