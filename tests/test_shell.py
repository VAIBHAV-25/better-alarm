"""The conversational shell: banner, plain-English REPL, menu fallback."""

import json

import pytest

from betteralarm import cli, interactive
from betteralarm.config import data_path


def read_doc():
    return json.loads(data_path().read_text())


@pytest.fixture
def no_clock(monkeypatch):
    """Stub the dashboard so shell tests don't enter the real run loop."""
    calls = []
    monkeypatch.setattr(cli, "cmd_run", lambda args: calls.append(True) or 0)
    return calls


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(interactive, "is_interactive", lambda: True)

    def script(*lines):
        replies = list(lines)

        def fake_input(prompt=""):
            print(prompt, end="")
            if not replies:
                raise EOFError
            return replies.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)

    return script


class TestBanner:
    def test_shows_name_and_hints(self, tty, capsys):
        tty("quit")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "better-alarm" in out
        assert "remind me in" in out  # teaches by example

    def test_shows_next_alarm(self, tty, capsys):
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        tty("quit")
        cli.main([])
        assert "late" in capsys.readouterr().out


class TestBannerExamples:
    def test_banner_teaches_with_example_block(self, tty, capsys):
        tty("quit")
        cli.main([])
        out = capsys.readouterr().out
        assert "Try these" in out
        assert "wake me at 7:30" in out
        assert "start the clock" in out


class TestActionTips:
    def test_tip_shown_after_an_action(self, tty, no_clock, capsys):
        tty("remind me in 5 minutes to breathe", "quit")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert out.count("tip:") >= 2  # one in the banner, one after the action

    def test_tips_off_hides_all_tips(self, tty, no_clock, capsys):
        cli.main(["config", "set", "tips", "false"])
        capsys.readouterr()
        tty("remind me in 5 minutes to breathe", "quit")
        assert cli.main([]) == 0
        assert "tip:" not in capsys.readouterr().out


class TestNaturalLanguage:
    def test_remind_me_in(self, tty, no_clock, capsys):
        tty("remind me in 25 minutes to stir the soup", "quit")
        assert cli.main([]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["label"] == "stir the soup"

    def test_wake_me_at(self, tty, no_clock, capsys):
        # time comes from the sentence; label and repeat prompted (defaults)
        tty("wake me at 7:30", "", "", "quit")
        assert cli.main([]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "once"
        assert alarm["at"].split("T")[1].startswith("07:30")

    def test_setting_an_alarm_autostarts_the_clock(self, tty, no_clock, capsys):
        tty("remind me in 25 minutes to stir the soup", "quit")
        assert cli.main([]) == 0
        assert no_clock  # the dashboard was started without asking
        assert "starting the clock" in capsys.readouterr().out.lower()

    def test_quit_warns_when_alarms_cannot_ring(self, tty, no_clock, capsys):
        tty("remind me in 25 minutes to stir the soup", "quit")
        assert cli.main([]) == 0
        assert "not ring unless" in capsys.readouterr().out.lower()

    def test_list_in_plain_words(self, tty, capsys):
        tty("show my alarms", "quit")
        assert cli.main([]) == 0
        assert "no alarms" in capsys.readouterr().out.lower()

    def test_unknown_input_is_gentle(self, tty, capsys):
        tty("flurble wurble", "quit")
        assert cli.main([]) == 0
        out = capsys.readouterr().out.lower()
        assert "didn't catch" in out or "not sure" in out

    def test_help_lists_examples(self, tty, capsys):
        tty("help", "quit")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "wake me at" in out
        assert "remind me in" in out


class TestSlashCommands:
    def test_slash_edit_goes_straight_to_edit(self, tty, capsys):
        tty("/edit", "quit")
        assert cli.main([]) == 0
        # no alarms yet, so the edit flow answers immediately
        assert "no alarms yet" in capsys.readouterr().out.lower()

    def test_slash_menu_opens_the_menu(self, tty, capsys):
        tty("/menu", "8")  # straight into the menu, then quit
        assert cli.main([]) == 0
        assert "What do you want to do" in capsys.readouterr().out

    def test_bare_slash_shows_the_palette(self, tty, capsys):
        tty("/", "quit")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "/add" in out and "/remind" in out and "/menu" in out

    def test_slash_typo_shows_the_palette(self, tty, capsys):
        tty("/frobnicate", "quit")
        assert cli.main([]) == 0
        assert "/add" in capsys.readouterr().out


class TestMenuFallback:
    def test_empty_enter_opens_menu_quit(self, tty, capsys):
        tty("", "14")  # menu option 14 = quit
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "What do you want to do" in out
        assert "clock" in out.lower()

    def test_menu_has_a_back_option(self, tty, capsys):
        tty("", "15", "quit")  # 15 = back to the prompt, then quit from there
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "back" in out.lower()

    def test_menu_items_explain_themselves(self, tty, capsys):
        tty("", "14")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "⏰" in out  # icons make it scannable
        assert "ring" in out.lower()  # the clock item says alarms ring there
        assert "countdown" in out.lower()  # list item explains what you'll see

    def test_menu_covers_the_new_features(self, tty, capsys):
        tty("", "14")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "Recurring reminder" in out
        assert "Skip" in out
        assert "vacation" in out.lower()  # pause/resume item
        assert "Pomodoro" in out
        assert "Timer" in out
        assert "Stopwatch" in out

    def test_menu_timer_flow(self, tty, monkeypatch, capsys):
        ran = []
        from betteralarm import cli as cli_mod

        monkeypatch.setattr(cli_mod, "cmd_timer", lambda args: ran.append(args.duration) or 0)
        tty("", "10", "15m", "quit")  # 10 = timer, asks how long
        assert cli.main([]) == 0
        assert ran == ["15m"]

    def test_menu_stopwatch_flow(self, tty, monkeypatch, capsys):
        ran = []
        from betteralarm import cli as cli_mod

        monkeypatch.setattr(cli_mod, "cmd_stopwatch", lambda args: ran.append(True) or 0)
        tty("", "11", "quit")  # 11 = stopwatch
        assert cli.main([]) == 0
        assert ran == [True]

    def test_menu_set_alarm_flow(self, tty, no_clock, capsys):
        tty("", "1", "2pm", "meeting", "", "quit")
        assert cli.main([]) == 0
        assert read_doc()["alarms"][0]["label"] == "meeting"

    def test_menu_recurring_flow(self, tty, no_clock, capsys):
        tty("", "3", "30m", "water", "quit")  # 3 = recurring reminder
        assert cli.main([]) == 0
        alarm = read_doc()["alarms"][0]
        assert alarm["type"] == "interval"
        assert alarm["label"] == "water"

    def test_menu_pause_toggle(self, tty, capsys):
        cli.main(["add", "9:25", "standup", "--repeat", "daily"])
        capsys.readouterr()
        tty("", "8", "quit")  # 8 = pause/resume toggle -> pauses
        assert cli.main([]) == 0
        doc = read_doc()
        assert doc["alarms"][0]["enabled"] is False
        assert doc["config"]["paused_ids"]
        tty("", "8", "quit")  # same item now resumes
        assert cli.main([]) == 0
        assert read_doc()["alarms"][0]["enabled"] is True


class TestExit:
    def test_ctrl_d_quits_cleanly(self, tty, capsys):
        tty()  # immediate EOF at the prompt
        assert cli.main([]) == 0

    def test_non_tty_still_prints_usage(self, capsys):
        assert cli.main([]) == 2
        assert "usage" in capsys.readouterr().err.lower()


class TestBannerComingUp:
    def test_banner_previews_upcoming_alarms(self, tty, capsys):
        cli.main(["add", "23:58", "late-one"])
        cli.main(["add", "23:59", "late-two"])
        capsys.readouterr()
        tty("quit")
        cli.main([])
        out = capsys.readouterr().out
        banner = out.split("Try these")[0]
        assert "late-one" in banner and "late-two" in banner
        assert "coming up" in banner.lower()


class TestDaemonAwareQuit:
    def test_no_pending_warning_when_daemon_runs(self, tty, monkeypatch, capsys):
        from betteralarm import daemon as daemon_mod

        monkeypatch.setattr(daemon_mod, "is_running", lambda: True)
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        tty("quit")
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "NOT ring" not in out  # the daemon has it covered

    def test_warning_still_shown_without_daemon(self, tty, monkeypatch, capsys):
        from betteralarm import daemon as daemon_mod

        monkeypatch.setattr(daemon_mod, "is_running", lambda: False)
        cli.main(["add", "23:59", "late"])
        capsys.readouterr()
        tty("quit")
        assert cli.main([]) == 0
        assert "NOT ring" in capsys.readouterr().out
