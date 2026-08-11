from datetime import datetime, time, timedelta

from betteralarm.config import Config
from betteralarm.models import Alarm
from betteralarm.render import build_frame, make_renderer, LogRenderer, PlainRenderer
from betteralarm.store import AppState

NOW = datetime(2026, 8, 11, 15, 48, 12)  # Tuesday


def state_with(*alarms, **config_kw):
    return AppState(config=Config(**config_kw), alarms=list(alarms))


def standup():
    return Alarm(id="e5f6a7b8", label="standup", type="repeat", time=time(9, 25), days=(0, 1, 2, 3, 4))


def tea_at(dt):
    return Alarm(id="a1b2c3d4", label="tea", type="once", at=dt)


class TestBuildFrameIdle:
    def test_clock_and_date(self):
        f = build_frame(state_with(), NOW, ringing=None, width=100, height=30)
        assert f.clock == "15:48:12"
        assert "Tue" in f.date_line and "Aug 11" in f.date_line
        assert f.big  # plenty of room
        assert f.ring_line is None

    def test_12h(self):
        f = build_frame(state_with(time_format="12"), NOW, ringing=None, width=100, height=30)
        assert f.clock == "3:48:12 PM"

    def test_no_alarms(self):
        f = build_frame(state_with(), NOW, ringing=None, width=100, height=30)
        assert "no alarms" in f.next_line.lower()
        assert f.alarm_rows == []

    def test_next_alarm_due_now_reads_naturally(self):
        f = build_frame(state_with(tea_at(NOW + timedelta(milliseconds=500))), NOW, ringing=None, width=100, height=30)
        assert "in now" not in f.next_line
        assert "tea now" in f.next_line

    def test_next_alarm_countdown(self):
        f = build_frame(state_with(tea_at(NOW + timedelta(minutes=17))), NOW, ringing=None, width=100, height=30)
        assert "tea" in f.next_line
        assert "17m" in f.next_line

    def test_alarm_rows_listed(self):
        f = build_frame(state_with(standup(), tea_at(NOW + timedelta(hours=1))), NOW, ringing=None, width=100, height=30)
        assert len(f.alarm_rows) == 2
        assert any("standup" in r for r in f.alarm_rows)

    def test_idle_status_keys(self):
        f = build_frame(state_with(), NOW, ringing=None, width=100, height=30)
        assert "q" in f.status

    def test_tiny_terminal_small_clock(self):
        f = build_frame(state_with(), NOW, ringing=None, width=40, height=8)
        assert f.big is False


class TestBuildFrameRinging:
    def test_ring_line_and_keys(self):
        alarm = tea_at(NOW)
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        assert f.ring_line is not None
        assert "tea" in f.ring_line
        assert "s" in f.status and "d" in f.status

    def test_no_flashing_ever(self):
        # a steady highlighted banner, not a strobe
        alarm = tea_at(NOW)
        s = state_with(alarm)
        for ms in (0, 250, 500, 750):
            f = build_frame(s, NOW + timedelta(milliseconds=ms), ringing=alarm, width=100, height=30)
            assert not hasattr(f, "flash")

    def test_unlabeled_alarm_uses_id(self):
        alarm = tea_at(NOW)
        alarm.label = ""
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        assert "a1b2c3d4" in f.ring_line

    def test_status_shows_snooze_minutes(self):
        alarm = tea_at(NOW)
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        assert "snooze 5" in f.status  # config default

    def test_status_shows_per_alarm_snooze(self):
        alarm = tea_at(NOW)
        alarm.snooze_minutes = 2
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        assert "snooze 2" in f.status

    def test_next_line_explains_unattended_policy(self):
        alarm = tea_at(NOW)
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        assert "auto" in f.next_line and "5m" in f.next_line

    def test_compose_draws_a_ring_banner_box(self):
        alarm = tea_at(NOW)
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        text = PlainRenderer().compose(f, width=100, height=30)
        assert "╭" in text and "╰" in text
        assert "RINGING" in text and "tea" in text

    def test_draw_banner_is_steady_never_inverted(self, capsys):
        # no full-screen invert, no strobing: a steady bold-yellow banner
        alarm = tea_at(NOW)
        f = build_frame(state_with(alarm), NOW, ringing=alarm, width=100, height=30)
        r = PlainRenderer()
        r.size = lambda: (100, 30)
        r.draw(f)
        out = capsys.readouterr().out
        assert "\x1b[7m" not in out and "\x1b[1;7m" not in out  # no reverse video at all
        assert "\x1b[1;33m" in out  # banner highlighted steadily


class TestBigClock12h:
    def test_ampm_letters_have_real_glyphs(self):
        from betteralarm import bigfont

        for ch in "APM":
            assert ch in bigfont.FONT, f"12h clock needs a glyph for {ch!r}"
            assert any("█" in row for row in bigfont.FONT[ch]), f"glyph {ch!r} is blank"


class TestRenderers:
    def test_make_renderer_plain_when_forced(self):
        assert isinstance(make_renderer(force_plain=True), LogRenderer)

    def test_fullscreen_requires_stdin_tty_too(self, monkeypatch):
        # keyboard reads stdin: fullscreen UI with no working keys would be a trap
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        assert isinstance(make_renderer(), LogRenderer)

    def test_log_renderer_emits_state_changes_only(self, capsys):
        r = LogRenderer()
        idle = build_frame(state_with(), NOW, ringing=None, width=80, height=24)
        with r:
            r.draw(idle)
            r.draw(idle)
        out = capsys.readouterr().out
        assert out.count("\n") == 1  # duplicate frame not re-logged

    def test_plain_renderer_paints_frame(self, capsys):
        r = PlainRenderer.__new__(PlainRenderer)  # skip __init__ side effects if any
        f = build_frame(state_with(standup()), NOW, ringing=None, width=80, height=24)
        text = r.compose(f, width=80, height=24)
        assert "15:48:12" not in text  # big font, not literal digits
        assert "standup" in text


class TestProgressBar:
    def test_no_progress_no_bar(self):
        f = build_frame(state_with(), NOW, ringing=None, width=100, height=30)
        text = PlainRenderer().compose(f, width=100, height=30)
        assert "▰" not in text

    def test_progress_renders_a_bar_with_percent(self):
        f = build_frame(state_with(), NOW, ringing=None, width=100, height=30)
        f.progress = 0.5
        text = PlainRenderer().compose(f, width=100, height=30)
        assert "▰" in text and "▱" in text
        assert "50%" in text

    def test_full_progress(self):
        f = build_frame(state_with(), NOW, ringing=None, width=100, height=30)
        f.progress = 1.0
        text = PlainRenderer().compose(f, width=100, height=30)
        assert "▱" not in text.split("100%")[0].splitlines()[-1]
