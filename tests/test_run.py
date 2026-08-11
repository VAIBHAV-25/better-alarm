import json
from datetime import datetime, timedelta

from betteralarm import run as run_mod
from betteralarm.config import Config, data_path
from betteralarm.models import Alarm
from betteralarm.store import AppState, Store

T0 = datetime(2026, 8, 11, 7, 29, 59)


class FakeClockKeyboard:
    """Scripted keys; each get_key advances a fake clock by the requested timeout."""

    def __init__(self, start, keys):
        self.now = start
        self.keys = list(keys)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def get_key(self, timeout):
        self.now += timedelta(seconds=timeout)
        return self.keys.pop(0) if self.keys else None


class RecordingPlayer:
    calls: list = []

    def start(self):
        RecordingPlayer.calls.append("start")

    def tick(self):
        pass

    def stop(self):
        RecordingPlayer.calls.append("stop")


def test_dashboard_rings_dismisses_and_quits(monkeypatch, capsys):
    RecordingPlayer.calls = []
    monkeypatch.setattr(run_mod, "make_player", lambda spec, cfg, **kw: RecordingPlayer())
    store = Store()
    alarm = Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=2))
    store.save(AppState(config=Config(), alarms=[alarm]))

    kb = FakeClockKeyboard(T0, [None, None, None, "d", "q"])
    rc = run_mod.run_dashboard(
        store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "RINGING" in out and "tea" in out
    assert RecordingPlayer.calls == ["start", "stop"]
    saved = json.loads(data_path().read_text())["alarms"][0]
    assert saved["enabled"] is False  # dismissal persisted


def test_dashboard_quits_immediately(capsys):
    store = Store()
    store.save(AppState(config=Config(), alarms=[]))
    kb = FakeClockKeyboard(T0, ["q"])
    assert run_mod.run_dashboard(store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now) == 0


def test_timer_exits_after_dismiss(monkeypatch, capsys):
    RecordingPlayer.calls = []
    monkeypatch.setattr(run_mod, "make_player", lambda spec, cfg, **kw: RecordingPlayer())
    kb = FakeClockKeyboard(T0, [None, None, None, "d"])
    rc = run_mod.run_timer(
        timedelta(seconds=2), "pasta", force_plain=True, keyboard=kb, now_fn=lambda: kb.now
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "pasta" in out
    # ephemeral: nothing persisted
    assert not data_path().exists()


def test_dirty_save_keeps_alarm_added_while_ringing(monkeypatch, capsys):
    """An `alarm add` from another terminal during a ring must survive the dismiss-save."""
    RecordingPlayer.calls = []
    monkeypatch.setattr(run_mod, "make_player", lambda spec, cfg, **kw: RecordingPlayer())
    store = Store()
    tea = Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=2))
    store.save(AppState(config=Config(), alarms=[tea]))

    class SneakyAddKeyboard(FakeClockKeyboard):
        def get_key(self, timeout):
            key = super().get_key(timeout)
            if key == "d":  # ringing right now; add from "another terminal"
                external = store.load()
                external.alarms.append(
                    Alarm(id="n1", label="meeting", type="once", at=T0 + timedelta(hours=1))
                )
                store.save(external)
            return key

    kb = SneakyAddKeyboard(T0, [None, None, None, "d", "q"])
    assert run_mod.run_dashboard(store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now) == 0
    doc = json.loads(data_path().read_text())
    by_id = {a["id"]: a for a in doc["alarms"]}
    assert set(by_id) == {"o1", "n1"}, "externally added alarm was lost by the dismiss-save"
    assert by_id["o1"]["enabled"] is False  # the dismissal itself persisted


def test_ctrl_c_exits_quietly_with_130(monkeypatch):
    class InterruptingKeyboard(FakeClockKeyboard):
        def get_key(self, timeout):
            raise KeyboardInterrupt

    store = Store()
    store.save(AppState(config=Config(), alarms=[]))
    kb = InterruptingKeyboard(T0, [])
    rc = run_mod.run_dashboard(store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now)
    assert rc == 130  # no traceback, conventional SIGINT code


def test_dashboard_live_reloads_new_alarms(monkeypatch, capsys):
    store = Store()
    store.save(AppState(config=Config(), alarms=[]))

    added = Alarm(id="n1", label="new", type="once", at=T0 + timedelta(hours=1))

    class ReloadingKeyboard(FakeClockKeyboard):
        def get_key(self, timeout):
            key = super().get_key(timeout)
            if len(self.keys) == 1:  # sneak a save in from "another terminal"
                state = store.load()
                if not state.alarms:
                    state.alarms.append(added)
                    store.save(state)
            return key

    kb = ReloadingKeyboard(T0, [None, None, None, "q"])
    run_mod.run_dashboard(store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now)
    assert "new" in capsys.readouterr().out


def test_ring_opens_url_and_notifies(monkeypatch, capsys):
    RecordingPlayer.calls = []
    monkeypatch.setattr(run_mod, "make_player", lambda spec, cfg, **kw: RecordingPlayer())
    opened, notified = [], []
    monkeypatch.setattr(run_mod, "_open_url", lambda url: opened.append(url))
    monkeypatch.setattr(run_mod, "notify", lambda title, msg: notified.append(title))
    store = Store()
    alarm = Alarm(
        id="o1", label="standup", type="once",
        at=T0 + timedelta(seconds=2), open_url="https://meet.example/x",
    )
    store.save(AppState(config=Config(), alarms=[alarm]))
    kb = FakeClockKeyboard(T0, [None, None, None, "d", "q"])
    assert run_mod.run_dashboard(store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now) == 0
    assert opened == ["https://meet.example/x"]
    assert notified and "standup" in notified[0]


def test_notifications_respect_config(monkeypatch, capsys):
    RecordingPlayer.calls = []
    monkeypatch.setattr(run_mod, "make_player", lambda spec, cfg, **kw: RecordingPlayer())
    notified = []
    monkeypatch.setattr(run_mod, "notify", lambda title, msg: notified.append(title))
    store = Store()
    alarm = Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=2))
    store.save(AppState(config=Config(notifications=False), alarms=[alarm]))
    kb = FakeClockKeyboard(T0, [None, None, None, "d", "q"])
    run_mod.run_dashboard(store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now)
    assert notified == []


class TestQuitAndSkipCodes:
    def test_q_returns_the_quit_rc(self):
        store = Store()
        store.save(AppState(config=Config(), alarms=[]))
        kb = FakeClockKeyboard(T0, ["q"])
        rc = run_mod.run_dashboard(
            store, force_plain=True, keyboard=kb, now_fn=lambda: kb.now, quit_rc=3
        )
        assert rc == 3

    def test_n_returns_the_skip_rc(self, capsys):
        kb = FakeClockKeyboard(T0, ["n"])
        rc = run_mod.run_timer(
            timedelta(minutes=5), "work", force_plain=True, keyboard=kb,
            now_fn=lambda: kb.now, skip_rc=4,
        )
        assert rc == 4

    def test_n_without_skip_rc_is_ignored(self, capsys):
        kb = FakeClockKeyboard(T0, ["n", "q"])
        rc = run_mod.run_timer(
            timedelta(minutes=5), "work", force_plain=True, keyboard=kb, now_fn=lambda: kb.now
        )
        assert rc == 0  # plain timers don't have phases; n does nothing


def test_timer_reports_progress(capsys):
    # the timer wires a progress fraction into the frame
    frames = []

    class SpyRenderer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def size(self):
            return (80, 24)

        def draw(self, frame):
            frames.append(frame.progress)

    kb = FakeClockKeyboard(T0, [None, None, "q"])
    run_mod.run_timer(
        timedelta(seconds=4), "pasta", keyboard=kb, now_fn=lambda: kb.now,
        renderer=SpyRenderer(),
    )
    real = [p for p in frames if p is not None]
    assert real and 0.0 <= real[0] <= 1.0
    assert real == sorted(real)  # advances monotonically
