"""Plain-English input → (action, prefills). The heart of the friendly shell."""

from betteralarm.intent import parse_intent


def act(text):
    return parse_intent(text).action


class TestSimpleActions:
    def test_quit(self):
        for text in ("quit", "exit", "q", "bye"):
            assert act(text) == "quit"

    def test_help(self):
        for text in ("help", "?", "what can you do"):
            assert act(text) == "help"

    def test_list(self):
        for text in ("list", "show my alarms", "what alarms do i have"):
            assert act(text) == "list"

    def test_run_the_clock(self):
        for text in ("start the clock", "run", "clock"):
            assert act(text) == "run"

    def test_edit(self):
        for text in ("edit", "change my alarm", "reschedule", "rename the alarm"):
            assert act(text) == "edit"

    def test_remove(self):
        for text in ("remove", "delete the tea alarm", "cancel my alarm"):
            assert act(text) == "remove"

    def test_settings(self):
        for text in ("settings", "config", "preferences"):
            assert act(text) == "settings"

    def test_stopwatch(self):
        assert act("stopwatch") == "stopwatch"

    def test_unknown(self):
        assert act("flurble wurble") == "unknown"


class TestAddIntent:
    def test_wake_me_at(self):
        intent = parse_intent("wake me at 7:30")
        assert intent.action == "add"
        assert intent.time == "7:30"

    def test_set_an_alarm_for(self):
        intent = parse_intent("set an alarm for 7pm")
        assert intent.action == "add"
        assert intent.time == "7pm"

    def test_alarm_at_with_minutes_and_ampm(self):
        intent = parse_intent("alarm at 6:45am")
        assert intent.action == "add"
        assert intent.time == "6:45am"

    def test_spaced_ampm_normalized(self):
        assert parse_intent("wake me at 7 pm").time == "7pm"

    def test_add_without_time(self):
        intent = parse_intent("set an alarm")
        assert intent.action == "add"
        assert intent.time is None

    def test_bare_time_is_add(self):
        intent = parse_intent("7:30")
        assert intent.action == "add"
        assert intent.time == "7:30"


class TestRemindIntent:
    def test_remind_me_in_minutes(self):
        intent = parse_intent("remind me in 25 minutes")
        assert intent.action == "in"
        assert intent.duration == "25m"

    def test_remind_with_label_after_duration(self):
        intent = parse_intent("remind me in 1 hour to stretch")
        assert intent.action == "in"
        assert intent.duration == "1h"
        assert intent.label == "stretch"

    def test_remind_with_label_before_duration(self):
        intent = parse_intent("remind me to drink water in 10 mins")
        assert intent.action == "in"
        assert intent.duration == "10m"
        assert intent.label == "drink water"

    def test_compact_duration_token(self):
        intent = parse_intent("in 90s")
        assert intent.action == "in"
        assert intent.duration == "90s"

    def test_bare_duration_is_remind(self):
        intent = parse_intent("25m")
        assert intent.action == "in"
        assert intent.duration == "25m"

    def test_timer(self):
        intent = parse_intent("timer 10m")
        assert intent.action == "timer"
        assert intent.duration == "10m"


class TestSlashCommands:
    def test_slash_maps_directly(self):
        assert act("/add") == "add"
        assert act("/list") == "list"
        assert act("/quit") == "quit"
        assert act("/remind") == "in"
        assert act("/settings") == "settings"
        assert act("/edit") == "edit"

    def test_slash_menu_opens_the_menu(self):
        assert act("/menu") == "menu"
        assert act("menu") == "menu"

    def test_bare_slash_lists_commands(self):
        assert act("/") == "commands"

    def test_unknown_slash_shows_commands_not_a_shrug(self):
        assert act("/frobnicate") == "commands"


class TestNaturalDates:
    def test_remind_me_tomorrow_at(self):
        intent = parse_intent("remind me tomorrow at 9am to submit the report")
        assert intent.action == "add"
        assert intent.time == "tomorrow 9am"
        assert intent.label == "submit the report"

    def test_wake_me_monday(self):
        intent = parse_intent("wake me monday at 7:30")
        assert intent.action == "add"
        assert intent.time == "monday 7:30"

    def test_alarm_tomorrow_bare_hour(self):
        intent = parse_intent("set an alarm tomorrow at 9")
        assert intent.action == "add"
        assert intent.time == "tomorrow 9"


class TestNewCommandIntents:
    def test_every_interval(self):
        intent = parse_intent("remind me every 30 minutes to drink water")
        assert intent.action == "every"
        assert intent.duration == "30m"
        assert intent.label == "drink water"

    def test_every_short(self):
        intent = parse_intent("every 1h stretch")
        assert intent.action == "every"
        assert intent.duration == "1h"

    def test_skip(self):
        assert act("skip") == "skip"
        assert act("skip tomorrow's alarm") == "skip"

    def test_pause_resume(self):
        assert act("pause") == "pause"
        assert act("pause my alarms") == "pause"
        assert act("resume") == "resume"

    def test_pomodoro(self):
        assert act("pomodoro") == "pomodoro"
        assert act("start a pomodoro") == "pomodoro"

    def test_slash_versions(self):
        assert act("/every") == "every"
        assert act("/skip") == "skip"
        assert act("/pause") == "pause"
        assert act("/resume") == "resume"
        assert act("/pomodoro") == "pomodoro"


class TestDaemonIntents:
    def test_daemon_words(self):
        assert act("/daemon") == "daemon"
        assert act("daemon") == "daemon"

    def test_dismiss_and_snooze(self):
        assert act("dismiss") == "dismiss"
        assert act("snooze") == "snooze"
        assert act("/dismiss") == "dismiss"
