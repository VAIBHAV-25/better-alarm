"""Conversational command flows: missing arguments become prompts (TTY only)."""

import json

import pytest

from betteralarm import cli, interactive
from betteralarm.config import data_path


def read_doc():
    return json.loads(data_path().read_text())


@pytest.fixture
def tty(monkeypatch):
    """Pretend a human is at the terminal and script their answers."""
    monkeypatch.setattr(interactive, "is_interactive", lambda: True)

    def script(*lines):
        replies = list(lines)

        def fake_input(prompt=""):
            print(prompt, end="")  # keep prompts visible to capsys assertions
            if not replies:
                raise EOFError
            return replies.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)

    return script


class TestInteractiveEdit:
    def seed(self):
        cli.main(["add", "9:25", "standup", "--repeat", "weekdays"])
        cli.main(["add", "23:59", "late"])

    def test_bare_edit_prompts_for_everything(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        # pick alarm 1 (standup), field 1 (time), new value, nothing else
        tty("1", "1", "10:00", "n")
        assert cli.main(["edit"]) == 0
        out = capsys.readouterr().out
        assert "standup" in out  # pick-list showed the alarms
        alarms = {a["label"]: a for a in read_doc()["alarms"]}
        assert alarms["standup"]["time"] == "10:00"

    def test_change_is_acknowledged_immediately(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty("1", "1", "10:00", "n")
        cli.main(["edit"])
        assert "time → 10:00" in capsys.readouterr().out

    def test_enter_at_anything_else_saves(self, tty, capsys):
        # the default answer finishes the edit — no explicit "done" step
        self.seed()
        capsys.readouterr()
        tty("1", "1", "10:00", "")
        assert cli.main(["edit"]) == 0
        alarms = {a["label"]: a for a in read_doc()["alarms"]}
        assert alarms["standup"]["time"] == "10:00"

    def test_yes_loops_with_updated_value_shown(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty("1", "1", "10:00", "y", "2", "sync", "n")
        assert cli.main(["edit"]) == 0
        out = capsys.readouterr().out
        # second menu shows the pending new time, not the stale one
        assert "(10:00)" in out
        alarms = {a["label"]: a for a in read_doc()["alarms"]}
        assert alarms["sync"]["time"] == "10:00"

    def test_edit_with_target_asks_what_to_change(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty("2", "sync", "n")  # field 2 = label, new value, nothing else
        assert cli.main(["edit", "standup"]) == 0
        labels = [a["label"] for a in read_doc()["alarms"]]
        assert "sync" in labels and "standup" not in labels

    def test_edit_shows_equivalent_one_liner(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty("1", "1", "10:00", "n")
        cli.main(["edit"])
        assert "alarm edit" in capsys.readouterr().out  # teaches the fast path

    def test_empty_answer_keeps_current_value(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty("1", "1", "", "n")  # Enter at the time prompt = keep 9:25
        assert cli.main(["edit"]) == 0
        alarms = {a["label"]: a for a in read_doc()["alarms"]}
        assert alarms["standup"]["time"] == "09:25"

    def test_bad_value_reprompts_instead_of_exiting(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty("1", "1", "25:99", "10:00", "n")
        assert cli.main(["edit"]) == 0
        alarms = {a["label"]: a for a in read_doc()["alarms"]}
        assert alarms["standup"]["time"] == "10:00"

    def test_repeat_shows_word_not_schedule(self, tty, capsys):
        cli.main(["add", "23:59", "late"])  # a once-alarm
        capsys.readouterr()
        tty("1", "1", "10:00", "n")
        cli.main(["edit"])
        assert "repeat  (once)" in capsys.readouterr().out

    def test_flags_still_work_no_prompts(self, capsys):
        self.seed()
        capsys.readouterr()
        assert cli.main(["edit", "standup", "--time", "10:00"]) == 0
        alarms = {a["label"]: a for a in read_doc()["alarms"]}
        assert alarms["standup"]["time"] == "10:00"

    def test_non_tty_bare_edit_errors_helpfully(self, capsys):
        self.seed()
        capsys.readouterr()
        assert cli.main(["edit"]) == 2
        assert "alarm" in capsys.readouterr().err.lower()

    def test_ctrl_d_cancels_cleanly(self, tty, capsys):
        self.seed()
        capsys.readouterr()
        tty()  # immediate EOF
        assert cli.main(["edit"]) == 1
        assert "cancel" in capsys.readouterr().out.lower()


class TestInteractiveAdd:
    def test_bare_add_prompts_time_label_repeat(self, tty, capsys):
        tty("2pm", "meeting", "")
        assert cli.main(["add"]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["label"] == "meeting"
        assert alarm["type"] == "once"
        assert alarm["at"].split("T")[1].startswith("14:00")
        assert "alarm add 2pm meeting" in capsys.readouterr().out

    def test_add_with_repeat_answer(self, tty):
        tty("7:30", "wake", "weekdays")
        assert cli.main(["add"]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "repeat"
        assert alarm["days"] == [0, 1, 2, 3, 4]

    def test_non_tty_bare_add_errors(self, capsys):
        assert cli.main(["add"]) == 2

    def test_tty_add_reminds_alarms_ring_in_the_clock(self, tty, capsys):
        tty()
        assert cli.main(["add", "23:59", "late"]) == 0
        assert "alarm run" in capsys.readouterr().out

    def test_non_tty_add_stays_script_clean(self, capsys):
        assert cli.main(["add", "23:59", "late"]) == 0
        assert "alarm run" not in capsys.readouterr().out


class TestInteractiveIn:
    def test_bare_in_prompts(self, tty, capsys):
        tty("25m", "tea")
        assert cli.main(["in"]) == 0
        assert read_doc()["alarms"][0]["label"] == "tea"
        assert "alarm in 25m tea" in capsys.readouterr().out

    def test_countdown_anchors_to_the_duration_answer(self, capsys):
        # a slow label answer must not delay the ring: 10s means 10s from when
        # the user said "10s", not from when they finished typing the label
        from datetime import datetime, timedelta
        from betteralarm.cli import build_parser, cmd_in

        args = build_parser().parse_args(["in", "2m", "tea"])
        args._anchor = datetime.now() - timedelta(seconds=90)  # typed label for 90s
        assert cmd_in(args) == 0
        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        remaining = at - datetime.now()
        assert timedelta(seconds=25) < remaining <= timedelta(seconds=30)

    def test_non_tty_bare_in_errors(self, capsys):
        assert cli.main(["in"]) == 2


class TestInteractiveRemove:
    def test_pick_and_confirm(self, tty, capsys):
        cli.main(["add", "9:25", "standup"])
        capsys.readouterr()
        tty("1", "y")
        assert cli.main(["remove"]) == 0
        assert read_doc()["alarms"] == []

    def test_confirm_no_keeps_alarm(self, tty, capsys):
        cli.main(["add", "9:25", "standup"])
        capsys.readouterr()
        tty("1", "n")
        assert cli.main(["remove"]) == 0
        assert len(read_doc()["alarms"]) == 1

    def test_remove_with_no_alarms_says_so(self, tty, capsys):
        tty()
        assert cli.main(["remove"]) == 0
        assert "no alarms" in capsys.readouterr().out.lower()

    def test_explicit_cancel_option_in_the_list(self, tty, capsys):
        cli.main(["add", "9:25", "standup"])
        capsys.readouterr()
        tty("2")  # 1) standup  2) ✕ cancel
        assert cli.main(["remove"]) == 0
        assert len(read_doc()["alarms"]) == 1
        assert "cancel" in capsys.readouterr().out.lower()


class TestInteractiveToggle:
    def test_disable_picks_from_list(self, tty, capsys):
        cli.main(["add", "9:25", "standup"])
        capsys.readouterr()
        tty("1")
        assert cli.main(["disable"]) == 0
        assert read_doc()["alarms"][0]["enabled"] is False


class TestInteractiveConfigSet:
    def test_pick_key_then_value(self, tty, capsys):
        tty("1", "10")  # first key in the pick-list is snooze_minutes
        assert cli.main(["config", "set"]) == 0
        assert read_doc()["config"]["snooze_minutes"] == 10

    def test_bad_value_reprompts(self, tty, capsys):
        tty("1", "zero", "10")
        assert cli.main(["config", "set"]) == 0
        assert read_doc()["config"]["snooze_minutes"] == 10


class TestDidYouMean:
    def test_typo_suggests_command(self, capsys):
        assert cli.main(["remvoe", "x"]) == 2
        assert "remove" in capsys.readouterr().err

    def test_gibberish_no_suggestion_no_crash(self, capsys):
        assert cli.main(["zzzzz"]) == 2


class TestFriendlyHelp:
    def test_help_is_task_oriented(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["--help"])
        out = capsys.readouterr().out
        assert "alarm in 25m tea" in out
        assert "alarm run" in out


class TestEditDate:
    def test_edit_time_accepts_a_natural_date(self, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        assert cli.main(["edit", "late", "--time", "tomorrow 9am"]) == 0
        from datetime import datetime, timedelta

        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        assert at.date() == (datetime.now() + timedelta(days=1)).date()
        assert (at.hour, at.minute) == (9, 0)

    def test_editing_a_repeat_to_a_date_makes_it_once(self, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "weekdays"])
        capsys.readouterr()
        assert cli.main(["edit", "standup", "--time", "aug 20 14:00"]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "once"
        assert alarm["at"].endswith("T14:00:00")
        assert alarm["days"] == []

    def test_date_plus_repeat_rejected(self, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        assert cli.main(["edit", "late", "--time", "tomorrow 9am", "--repeat", "daily"]) == 2

    def test_interactive_edit_accepts_a_date(self, tty, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        tty("1", "1", "tomorrow 9am", "n")
        assert cli.main(["edit"]) == 0
        from datetime import datetime, timedelta

        at = datetime.fromisoformat(read_doc()["alarms"][0]["at"])
        assert at.date() == (datetime.now() + timedelta(days=1)).date()


class TestPickListCancel:
    def test_edit_alarm_list_has_cancel(self, tty, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        tty("2")  # 1) late  2) cancel
        assert cli.main(["edit"]) == 0
        out = capsys.readouterr().out.lower()
        assert "cancel" in out
        assert read_doc()["alarms"][0]["at"].endswith("T23:59:00")  # untouched

    def test_edit_field_menu_has_cancel(self, tty, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        tty("1", "6")  # pick alarm, then field option 6 = cancel
        assert cli.main(["edit"]) == 0
        assert "cancel" in capsys.readouterr().out.lower()

    def test_skip_list_has_cancel(self, tty, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "daily"])
        capsys.readouterr()
        tty("2")
        assert cli.main(["skip"]) == 0
        assert read_doc()["alarms"][0]["skip_until"] is None  # nothing skipped

    def test_disable_list_has_cancel(self, tty, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "daily"])
        capsys.readouterr()
        tty("2")
        assert cli.main(["disable"]) == 0
        assert read_doc()["alarms"][0]["enabled"] is True  # untouched
