from datetime import datetime, time
from pathlib import Path

from betteralarm.config import Config, data_dir, data_path
from betteralarm.models import Alarm, new_id


class TestAlarm:
    def test_once_roundtrip(self):
        a = Alarm(
            id="a1b2c3d4",
            label="tea",
            type="once",
            at=datetime(2026, 8, 11, 16, 5),
        )
        b = Alarm.from_dict(a.to_dict())
        assert b == a

    def test_repeat_roundtrip(self):
        a = Alarm(
            id="e5f6a7b8",
            label="standup",
            type="repeat",
            time=time(9, 25),
            days=(0, 1, 2, 3, 4),
            sound="bell",
            snooze_minutes=5,
            snooze_until=datetime(2026, 8, 11, 9, 30),
        )
        assert Alarm.from_dict(a.to_dict()) == a

    def test_to_dict_is_json_native(self):
        a = Alarm(id="x", label="", type="repeat", time=time(9, 25), days=(0, 4))
        d = a.to_dict()
        assert d["time"] == "09:25"
        assert d["days"] == [0, 4]
        assert d["at"] is None
        assert isinstance(d["created_at"], str)

    def test_from_dict_ignores_unknown_keys(self):
        a = Alarm(id="x", label="l", type="once", at=datetime(2026, 1, 1, 8, 0))
        d = a.to_dict() | {"future_field": 42}
        assert Alarm.from_dict(d) == a

    def test_from_dict_defaults_missing_keys(self):
        a = Alarm.from_dict({"id": "x", "type": "once", "at": "2026-01-01T08:00:00"})
        assert a.enabled is True
        assert a.sound == "default"
        assert a.label == ""
        assert a.days == ()

    def test_from_dict_rejects_once_without_at(self):
        import pytest

        with pytest.raises(ValueError):
            Alarm.from_dict({"id": "x", "type": "once", "at": None})

    def test_from_dict_rejects_repeat_without_time(self):
        import pytest

        with pytest.raises(ValueError):
            Alarm.from_dict({"id": "x", "type": "repeat", "days": [0]})

    def test_from_dict_rejects_unknown_type(self):
        import pytest

        with pytest.raises(ValueError):
            Alarm.from_dict({"id": "x", "type": "sometimes"})

    def test_new_id_short_and_unique(self):
        ids = {new_id() for _ in range(100)}
        assert len(ids) == 100
        assert all(len(i) == 8 for i in ids)


class TestDescribeSchedule:
    def test_daily(self):
        a = Alarm(id="x", label="", type="repeat", time=time(7, 30), days=tuple(range(7)))
        assert a.describe_schedule("24") == "daily 07:30"

    def test_weekdays(self):
        a = Alarm(id="x", label="", type="repeat", time=time(9, 25), days=(0, 1, 2, 3, 4))
        assert a.describe_schedule("24") == "weekdays 09:25"

    def test_weekends_12h(self):
        a = Alarm(id="x", label="", type="repeat", time=time(19, 30), days=(5, 6))
        assert a.describe_schedule("12") == "weekends 7:30 PM"

    def test_custom_days(self):
        a = Alarm(id="x", label="", type="repeat", time=time(6, 0), days=(0, 2, 4))
        assert a.describe_schedule("24") == "mon,wed,fri 06:00"

    def test_once(self):
        a = Alarm(id="x", label="", type="once", at=datetime(2026, 8, 11, 16, 5))
        assert a.describe_schedule("24") == "Aug 11 16:05"


class TestConfig:
    def test_defaults(self):
        c = Config()
        assert c.snooze_minutes == 5
        assert c.time_format == "24"
        assert c.sound_enabled is True
        assert c.auto_action == "snooze"
        assert c.auto_action_minutes == 5
        assert c.max_auto_snoozes == 3

    def test_roundtrip(self):
        c = Config(snooze_minutes=5, time_format="12", default_sound="bell")
        assert Config.from_dict(c.to_dict()) == c

    def test_from_dict_tolerant(self):
        assert Config.from_dict({"unknown": 1}) == Config()

    def test_from_dict_normalizes_bad_enums(self):
        # hand-edited files shouldn't silently change behavior
        c = Config.from_dict({"time_format": "13", "auto_action": "Dismiss"})
        assert c.time_format == "24"
        assert c.auto_action == "dismiss"


class TestPaths:
    def test_env_override(self, isolated_store):
        assert data_dir() == Path(isolated_store)
        assert data_path() == Path(isolated_store) / "alarms.json"

    def test_default_is_home(self, monkeypatch):
        monkeypatch.delenv("BETTER_ALARM_HOME")
        assert data_dir() == Path.home() / ".better-alarm"
