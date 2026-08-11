"""The background ringer: headless engine loop, service files, coordination."""

import os
import time
from datetime import datetime, timedelta

import pytest

from betteralarm import daemon
from betteralarm.config import Config, data_dir
from betteralarm.models import Alarm
from betteralarm.store import AppState, Store

T0 = datetime(2026, 8, 11, 7, 29, 59)


class FakeClock:
    """now_fn/sleep_fn pair: sleeping advances the fake time."""

    def __init__(self, start):
        self.now = start

    def now_fn(self):
        return self.now

    def sleep_fn(self, seconds):
        self.now += timedelta(seconds=seconds)


class RecPlayer:
    started = 0
    stopped = 0

    def start(self):
        RecPlayer.started += 1

    def tick(self):
        pass

    def stop(self):
        RecPlayer.stopped += 1


@pytest.fixture(autouse=True)
def _reset_recplayer():
    RecPlayer.started = RecPlayer.stopped = 0


def run_loop(store, clock, iterations, notes):
    return daemon.daemon_loop(
        store,
        iterations=iterations,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
        notify_fn=lambda title, msg: notes.append(title),
        player_factory=lambda spec, cfg: RecPlayer(),
    )


class TestDaemonLoop:
    def test_fires_notification_and_sound(self):
        store = Store()
        store.save(AppState(config=Config(), alarms=[
            Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=2)),
        ]))
        clock = FakeClock(T0)
        notes = []
        run_loop(store, clock, iterations=8, notes=notes)
        assert RecPlayer.started >= 1
        assert any("tea" in n for n in notes)

    def test_external_dismiss_stops_the_ring(self):
        store = Store()
        alarm = Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=1))
        store.save(AppState(config=Config(), alarms=[alarm]))
        clock = FakeClock(T0)
        notes = []

        fired = run_loop(store, clock, iterations=4, notes=notes)
        assert fired.phase.name == "RINGING"

        # another terminal runs `alarm dismiss`: the file changes
        time.sleep(0.02)  # mtime must move
        disk = store.load()
        disk.alarms[0].enabled = False
        disk.alarms[0].last_dismissed = clock.now
        store.save(disk)

        engine = daemon.daemon_loop(
            store, iterations=3, now_fn=clock.now_fn, sleep_fn=clock.sleep_fn,
            notify_fn=lambda *a: None, player_factory=lambda s, c: RecPlayer(),
        )
        assert engine.phase.name == "IDLE"

    def test_auto_snooze_ends_the_ring_and_persists(self):
        store = Store()
        store.save(AppState(
            config=Config(auto_action_minutes=1),
            alarms=[Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=1))],
        ))
        clock = FakeClock(T0)
        notes = []
        run_loop(store, clock, iterations=300, notes=notes)  # sleeps push past 1 min
        saved = store.load()
        assert saved.alarms[0].snooze_until is not None  # auto-snooze persisted
        assert RecPlayer.stopped >= 1

    def test_defers_to_a_live_clock(self):
        store = Store()
        store.save(AppState(config=Config(), alarms=[
            Alarm(id="o1", label="tea", type="once", at=T0 + timedelta(seconds=1)),
        ]))
        daemon.touch_heartbeat()  # a fullscreen clock is running
        clock = FakeClock(T0)
        notes = []
        run_loop(store, clock, iterations=6, notes=notes)
        assert RecPlayer.started == 0  # the clock owns the ring
        assert notes == []


class TestHeartbeat:
    def test_fresh_heartbeat_detected(self):
        daemon.touch_heartbeat()
        assert daemon.clock_is_running() is True

    def test_stale_heartbeat_ignored(self):
        daemon.touch_heartbeat()
        old = time.time() - 60
        os.utime(daemon.heartbeat_path(), (old, old))
        assert daemon.clock_is_running() is False

    def test_missing_heartbeat(self):
        assert daemon.clock_is_running() is False


class TestServiceFiles:
    def test_launchd_plist_content(self):
        plist = daemon.launchd_plist("/usr/bin/python3")
        assert "com.better-alarm.daemon" in plist
        assert "/usr/bin/python3" in plist
        assert "betteralarm" in plist and "daemon" in plist
        assert "KeepAlive" in plist

    def test_systemd_unit_content(self):
        unit = daemon.systemd_unit("/usr/bin/python3")
        assert "ExecStart=/usr/bin/python3 -m betteralarm daemon run" in unit
        assert "Restart=always" in unit

    def test_plist_carries_data_home_override(self, monkeypatch):
        monkeypatch.setenv("BETTER_ALARM_HOME", "/tmp/custom")
        plist = daemon.launchd_plist("/usr/bin/python3")
        assert "BETTER_ALARM_HOME" in plist and "/tmp/custom" in plist


class TestInstall:
    def test_install_macos_writes_plist_and_loads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(daemon.sys, "platform", "darwin")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
        calls = []
        monkeypatch.setattr(
            daemon.subprocess, "run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        daemon.install()
        plist = tmp_path / "Library" / "LaunchAgents" / "com.better-alarm.daemon.plist"
        assert plist.exists()
        assert any("launchctl" in c[0] for c in calls)

    def test_uninstall_macos_removes_plist(self, monkeypatch, tmp_path):
        monkeypatch.setattr(daemon.sys, "platform", "darwin")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
        monkeypatch.setattr(
            daemon.subprocess, "run",
            lambda cmd, **kw: type("R", (), {"returncode": 0})(),
        )
        daemon.install()
        daemon.uninstall()
        plist = tmp_path / "Library" / "LaunchAgents" / "com.better-alarm.daemon.plist"
        assert not plist.exists()


class TestRemoteControl:
    """`alarm dismiss` / `alarm snooze` act on whatever is due right now."""

    def test_snooze_sets_snooze_until(self, capsys):
        from betteralarm import cli
        from betteralarm.config import data_path
        import json

        store = Store()
        store.save(AppState(config=Config(), alarms=[
            Alarm(id="o1", label="tea", type="once", at=datetime.now() - timedelta(seconds=30)),
        ]))
        assert cli.main(["snooze", "3"]) == 0
        doc = json.loads(data_path().read_text())
        assert doc["alarms"][0]["snooze_until"] is not None
        assert "3" in capsys.readouterr().out

    def test_dismiss_disables_due_once_alarm(self, capsys):
        from betteralarm import cli
        from betteralarm.config import data_path
        import json

        store = Store()
        store.save(AppState(config=Config(), alarms=[
            Alarm(id="o1", label="tea", type="once", at=datetime.now() - timedelta(seconds=30)),
        ]))
        assert cli.main(["dismiss"]) == 0
        doc = json.loads(data_path().read_text())
        assert doc["alarms"][0]["enabled"] is False

    def test_nothing_due_says_so(self, capsys):
        from betteralarm import cli

        Store().save(AppState(config=Config(), alarms=[]))
        assert cli.main(["dismiss"]) == 1
        assert "nothing" in capsys.readouterr().out.lower()
