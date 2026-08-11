import json
from datetime import datetime, timedelta

import pytest

from betteralarm import cli
from betteralarm.config import Config, data_path
from betteralarm.models import Alarm
from betteralarm.store import AppState, Store


def read_doc():
    return json.loads(data_path().read_text())


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_no_args_shows_help(capsys):
    rc = cli.main([])
    assert rc == 2
    assert "usage" in capsys.readouterr().err.lower()


class TestAdd:
    def test_basic(self, capsys):
        assert cli.main(["add", "23:59", "late"]) == 0
        out = capsys.readouterr().out
        assert "late" in out
        assert "23:59" in out
        assert "rings in" in out
        doc = read_doc()
        assert len(doc["alarms"]) == 1
        assert doc["alarms"][0]["type"] == "once"

    def test_past_time_rolls_to_tomorrow(self):
        cli.main(["add", "00:00", "midnight"])  # 00:00 today is always past
        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        assert at > datetime.now()

    def test_repeat(self, capsys):
        assert cli.main(["add", "9:25", "standup", "--repeat", "weekdays"]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "repeat"
        assert alarm["days"] == [0, 1, 2, 3, 4]
        assert alarm["time"] == "09:25"

    def test_options(self):
        cli.main(["add", "7:00", "--sound", "bell", "--snooze", "5", "--disabled"])
        alarm = read_doc()["alarms"][0]
        assert alarm["sound"] == "bell"
        assert alarm["snooze_minutes"] == 5
        assert alarm["enabled"] is False

    def test_invalid_time(self, capsys):
        assert cli.main(["add", "25:00"]) == 2
        assert "7:30" in capsys.readouterr().err  # helpful format hint

    def test_invalid_repeat(self, capsys):
        assert cli.main(["add", "7:00", "--repeat", "blursday"]) == 2

    def test_nonpositive_snooze_rejected(self, capsys):
        assert cli.main(["add", "7:00", "--snooze", "0"]) == 2
        assert cli.main(["add", "7:00", "--snooze", "-5"]) == 2
        capsys.readouterr()
        cli.main(["add", "7:00", "nap"])
        assert cli.main(["edit", "nap", "--snooze", "0"]) == 2


class TestIn:
    def test_relative(self, capsys):
        assert cli.main(["in", "25m", "tea"]) == 0
        out = capsys.readouterr().out
        assert "tea" in out
        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        delta = at - datetime.now()
        assert timedelta(minutes=24) < delta <= timedelta(minutes=25)

    def test_invalid(self, capsys):
        assert cli.main(["in", "eleventy"]) == 2


class TestList:
    def test_empty(self, capsys):
        assert cli.main(["list"]) == 0
        assert "no alarms" in capsys.readouterr().out.lower()

    def test_table(self, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "weekdays"])
        capsys.readouterr()
        cli.main(["list"])
        out = capsys.readouterr().out
        assert "standup" in out
        assert "weekdays 09:25" in out
        assert "in " in out

    def test_disabled_hidden_unless_all(self, capsys):
        cli.main(["add", "9:25", "hidden", "--disabled"])
        capsys.readouterr()
        cli.main(["list"])
        assert "hidden" not in capsys.readouterr().out
        cli.main(["list", "--all"])
        out = capsys.readouterr().out
        assert "hidden" in out
        assert "off" in out.lower()

    def test_missed_swept(self, capsys):
        store = Store()
        past = Alarm(id="m1", label="oops", type="once", at=datetime.now() - timedelta(hours=2))
        store.save(AppState(config=Config(), alarms=[past]))
        cli.main(["list"])
        out = capsys.readouterr().out
        assert "MISSED" in out
        assert "oops" in out
        assert read_doc()["alarms"][0]["enabled"] is False


class TestNext:
    def test_shows_next(self, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        assert cli.main(["next"]) == 0
        out = capsys.readouterr().out
        assert "late" in out
        assert "rings in" in out

    def test_none_exit_1(self, capsys):
        assert cli.main(["next"]) == 1


class TestRemoveEditToggle:
    def add_one(self, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "weekdays"])
        alarm_id = read_doc()["alarms"][0]["id"]
        capsys.readouterr()
        return alarm_id

    def test_remove_by_label(self, capsys):
        self.add_one(capsys)
        assert cli.main(["remove", "standup"]) == 0
        assert read_doc()["alarms"] == []

    def test_rm_by_id_prefix(self, capsys):
        alarm_id = self.add_one(capsys)
        assert cli.main(["rm", alarm_id[:4]]) == 0
        assert read_doc()["alarms"] == []

    def test_remove_missing(self, capsys):
        assert cli.main(["remove", "ghost"]) == 2
        assert "no alarm" in capsys.readouterr().err

    def test_edit(self, capsys):
        self.add_one(capsys)
        assert cli.main(["edit", "standup", "--time", "10:00", "--label", "sync"]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["time"] == "10:00"
        assert alarm["label"] == "sync"

    def test_edit_repeat_to_once(self, capsys):
        self.add_one(capsys)
        cli.main(["edit", "standup", "--repeat", "once"])
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "once"
        # keeps the alarm's own 9:25, not the current wall-clock instant
        at = datetime.fromisoformat(alarm["at"])
        assert (at.hour, at.minute) == (9, 25)

    def test_edit_repeat_once_with_time_uses_that_time(self, capsys):
        self.add_one(capsys)
        cli.main(["edit", "standup", "--repeat", "once", "--time", "11:00"])
        alarm = read_doc()["alarms"][0]
        at = datetime.fromisoformat(alarm["at"])
        assert (at.hour, at.minute) == (11, 0)

    def test_edit_once_alarm_to_once_is_noop_on_time(self, capsys):
        cli.main(["add", "23:58", "late"])
        capsys.readouterr()
        before = read_doc()["alarms"][0]["at"]
        cli.main(["edit", "late", "--repeat", "once"])
        assert read_doc()["alarms"][0]["at"] == before

    def test_edit_time_clears_pending_snooze(self, capsys):
        self.add_one(capsys)
        store = Store()
        state = store.load()
        state.alarms[0].snooze_until = datetime.now() + timedelta(minutes=5)
        store.save(state)
        cli.main(["edit", "standup", "--time", "10:00"])
        assert read_doc()["alarms"][0]["snooze_until"] is None

    def test_disable_enable(self, capsys):
        self.add_one(capsys)
        cli.main(["disable", "standup"])
        assert read_doc()["alarms"][0]["enabled"] is False
        cli.main(["enable", "standup"])
        assert read_doc()["alarms"][0]["enabled"] is True


class TestConfig:
    def test_show(self, capsys):
        assert cli.main(["config", "show"]) == 0
        out = capsys.readouterr().out
        assert "snooze_minutes = 5" in out  # default snooze is 5 minutes
        assert "tips = True" in out

    def test_get(self, capsys):
        cli.main(["config", "get", "time_format"])
        assert capsys.readouterr().out.strip() == "24"

    def test_set(self, capsys):
        assert cli.main(["config", "set", "snooze_minutes", "5"]) == 0
        assert read_doc()["config"]["snooze_minutes"] == 5

    def test_set_bool(self):
        cli.main(["config", "set", "sound_enabled", "false"])
        assert read_doc()["config"]["sound_enabled"] is False

    def test_set_unknown_key(self, capsys):
        assert cli.main(["config", "set", "bogus", "1"]) == 2

    def test_set_invalid_value(self, capsys):
        assert cli.main(["config", "set", "time_format", "13"]) == 2
        assert cli.main(["config", "set", "auto_action", "explode"]) == 2

    def test_set_zero_minutes_rejected(self, capsys):
        # snooze/auto-action of 0 minutes would refire or dismiss instantly
        assert cli.main(["config", "set", "snooze_minutes", "0"]) == 2
        assert cli.main(["config", "set", "auto_action_minutes", "0"]) == 2
        assert cli.main(["config", "set", "max_auto_snoozes", "0"]) == 0  # 0 is meaningful here


class TestJsonOutput:
    def test_list_json(self, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        assert cli.main(["list", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data[0]["label"] == "late"
        assert data[0]["next_ring"] is not None  # ISO timestamp

    def test_list_json_is_pure_json_even_with_missed(self, capsys):
        # MISSED lines must not corrupt the JSON document
        store = Store()
        past = Alarm(id="m1", label="oops", type="once", at=datetime.now() - timedelta(hours=2))
        store.save(AppState(config=Config(), alarms=[past]))
        cli.main(["list", "--json", "--all"])
        json.loads(capsys.readouterr().out)  # parses cleanly

    def test_next_json(self, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        assert cli.main(["next", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["label"] == "late"
        assert data["in_seconds"] > 0

    def test_next_json_empty(self, capsys):
        assert cli.main(["next", "--json"]) == 1
        assert json.loads(capsys.readouterr().out) is None


class TestNaturalDatesCli:
    def test_add_tomorrow(self):
        assert cli.main(["add", "tomorrow 9am", "gym"]) == 0
        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        assert at.date() == (datetime.now() + timedelta(days=1)).date()
        assert (at.hour, at.minute) == (9, 0)

    def test_when_plus_repeat_rejected(self, capsys):
        assert cli.main(["add", "tomorrow 9am", "gym", "--repeat", "daily"]) == 2

    def test_bad_when_helpful_error(self, capsys):
        assert cli.main(["add", "someday"]) == 2
        assert "tomorrow" in capsys.readouterr().err


class TestTimezone:
    def test_add_with_tz_converts_to_local(self):
        from zoneinfo import ZoneInfo

        assert cli.main(["add", "12:00", "call", "--tz", "UTC"]) == 0
        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        expected = (
            datetime.combine(datetime.now().date(), datetime.min.time())
            .replace(hour=12, tzinfo=ZoneInfo("UTC"))
            .astimezone()
            .replace(tzinfo=None)
        )
        if expected <= datetime.now():
            expected += timedelta(days=1)
        assert at == expected

    def test_unknown_tz_helpful_error(self, capsys):
        assert cli.main(["add", "12:00", "--tz", "Mars/Olympus"]) == 2
        assert "Kolkata" in capsys.readouterr().err  # example in the hint

    def test_repeat_with_tz_shifts_the_time(self):
        from zoneinfo import ZoneInfo

        assert cli.main(["add", "12:00", "sync", "--repeat", "daily", "--tz", "UTC"]) == 0
        stored = read_doc()["alarms"][0]["time"]
        local = (
            datetime.combine(datetime.now().date(), datetime.min.time())
            .replace(hour=12, tzinfo=ZoneInfo("UTC"))
            .astimezone()
        )
        assert stored == local.strftime("%H:%M")


class TestSkipPauseResume:
    def test_skip_repeat_pushes_past_next_ring(self, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "daily"])
        capsys.readouterr()
        assert cli.main(["skip", "standup"]) == 0
        out = capsys.readouterr().out
        assert "skip" in out.lower()
        assert read_doc()["alarms"][0]["skip_until"] is not None

    def test_skip_once_disables(self, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        assert cli.main(["skip", "late"]) == 0
        assert read_doc()["alarms"][0]["enabled"] is False

    def test_pause_and_resume_roundtrip(self, capsys):
        cli.main(["add", "9:25", "a", "--repeat", "daily"])
        cli.main(["add", "10:25", "b", "--repeat", "daily"])
        cli.main(["add", "11:25", "c", "--disabled"])
        capsys.readouterr()
        assert cli.main(["pause"]) == 0
        doc = read_doc()
        assert all(not a["enabled"] for a in doc["alarms"])
        assert len(doc["config"]["paused_ids"]) == 2  # only the ones pause switched off
        assert cli.main(["resume"]) == 0
        doc = read_doc()
        by_label = {a["label"]: a["enabled"] for a in doc["alarms"]}
        assert by_label == {"a": True, "b": True, "c": False}  # c stays off
        assert doc["config"]["paused_ids"] == []


class TestEvery:
    def test_every_creates_interval_alarm(self, capsys):
        assert cli.main(["every", "30m", "water"]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "interval"
        assert alarm["interval_seconds"] == 1800
        assert "every 30m" in capsys.readouterr().out

    def test_every_invalid_duration(self, capsys):
        assert cli.main(["every", "nope"]) == 2


class TestPomodoro:
    def test_spec_parses_into_phases(self):
        from betteralarm.cli import parse_pomodoro

        phases = parse_pomodoro("25/5x2")
        assert [(label.split()[0], d.total_seconds() / 60) for label, d in phases] == [
            ("work", 25), ("break", 5), ("work", 25),
        ]  # no trailing break after the last round

    def test_default_spec(self):
        from betteralarm.cli import parse_pomodoro

        assert len(parse_pomodoro(None)) == 7  # 25/5 x4 -> 4 work + 3 breaks

    def test_bad_spec(self):
        import pytest
        from betteralarm.cli import parse_pomodoro

        with pytest.raises(ValueError):
            parse_pomodoro("banana")

    def test_command_runs_phases_in_order(self, monkeypatch, capsys):
        ran = []
        from betteralarm import cli as cli_mod

        monkeypatch.setattr(
            cli_mod, "_run_timer_phase", lambda dur, label, *a: ran.append(label) or 0
        )
        assert cli.main(["pomodoro", "10/2x2"]) == 0
        assert len(ran) == 3
        assert ran[0].startswith("work") and ran[1].startswith("break")


class TestPomodoroEscape:
    def test_q_stops_the_whole_pomodoro(self, monkeypatch, capsys):
        from betteralarm import cli as cli_mod

        ran = []
        monkeypatch.setattr(
            cli_mod, "_run_timer_phase",
            lambda dur, label, *a: ran.append(label) or cli_mod._POMO_STOP,
        )
        assert cli.main(["pomodoro", "10/2x3"]) == 0  # intentional exit, clean rc
        assert len(ran) == 1  # stopped after the first phase, no break started
        assert "stopped" in capsys.readouterr().out.lower()

    def test_n_skips_only_the_current_phase(self, monkeypatch, capsys):
        from betteralarm import cli as cli_mod

        ran = []
        monkeypatch.setattr(
            cli_mod, "_run_timer_phase",
            lambda dur, label, *a: ran.append(label) or cli_mod._POMO_SKIP,
        )
        assert cli.main(["pomodoro", "10/2x2"]) == 0
        assert len(ran) == 3  # every phase offered, each skipped


class TestVisualHelpers:
    def test_countdown_urgency_styles(self):
        from betteralarm.cli import _countdown_style

        assert _countdown_style(timedelta(minutes=3)) == "red"
        assert _countdown_style(timedelta(minutes=45)) == "yellow"
        assert _countdown_style(timedelta(hours=5)) is None

    def test_pomodoro_footer_shows_rounds(self):
        from betteralarm.cli import _pomodoro_footer

        footer = _pomodoro_footer(done=2, total=4, label="work 3/4")
        assert "🍅🍅" in footer
        assert "3/4" in footer
        assert "[q]" in footer and "[n]" in footer
