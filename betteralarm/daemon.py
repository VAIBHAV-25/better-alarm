"""The background ringer: alarms fire with no terminal open.

`alarm daemon run` is a headless run loop over the same pure Engine the
dashboard uses — sound, desktop notification, auto-snooze policy and all.
`alarm daemon install` registers it with launchd (macOS) or a systemd user
unit (Linux) so it survives logout/login.

Coordination: while a fullscreen `alarm run` clock is open it touches a
heartbeat file; the daemon sees it and stays silent, so nothing rings twice.
Control: `alarm snooze` / `alarm dismiss` edit the data file from any
terminal; the daemon notices the change and ends the ring.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import data_dir
from .engine import Dirty, Dismissed, Engine, Fired, Missed, Phase, Snoozed
from .errors import UserError
from .notify import notify
from .sound import make_player
from .store import Store

IDLE_TICK = 1.0
RING_TICK = 0.25
HEARTBEAT_MAX_AGE = 5.0

LABEL = "com.better-alarm.daemon"

# ------------------------------------------------------------------ heartbeat


def heartbeat_path() -> Path:
    return data_dir() / "clock.alive"


def touch_heartbeat() -> None:
    path = heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def clear_heartbeat() -> None:
    heartbeat_path().unlink(missing_ok=True)


def clock_is_running() -> bool:
    try:
        return time.time() - heartbeat_path().stat().st_mtime < HEARTBEAT_MAX_AGE
    except OSError:
        return False


# ------------------------------------------------------------------ the loop


def _ring_resolved_externally(engine: Engine, now: datetime) -> bool:
    """Did `alarm dismiss`/`alarm snooze` (or an edit) handle the current ring?"""
    assert engine.session is not None
    alarm = next((a for a in engine.state.alarms if a.id == engine.session.alarm_id), None)
    if alarm is None or not alarm.enabled:
        return True
    if alarm.snooze_until and alarm.snooze_until > now:
        return True
    if alarm.last_dismissed and alarm.last_dismissed >= engine.session.target:
        return True
    return False


def daemon_loop(
    store: Store,
    *,
    iterations: int | None = None,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    notify_fn: Callable[[str, str], None] | None = None,
    player_factory=None,
) -> Engine:
    """Headless ring loop. All effects injectable; returns the engine (tests)."""
    now_fn = now_fn or datetime.now
    sleep_fn = sleep_fn or time.sleep
    notify_fn = notify_fn or notify
    player_factory = player_factory or (
        lambda spec, cfg: make_player(spec, cfg, insistent=True)
    )

    engine = Engine(store.load())
    player = None
    now = now_fn()
    loaded_mtime = store.mtime()

    def save_merged(current: datetime) -> None:
        """Persist our changes without clobbering edits from other terminals."""
        nonlocal loaded_mtime
        if store.mtime() != loaded_mtime:
            disk = store.load()
            ours = {a.id: a for a in engine.state.alarms}
            disk.alarms = [ours.get(alarm.id, alarm) for alarm in disk.alarms]
            engine.state = disk
            engine.recompute(current)
        store.save(engine.state)
        loaded_mtime = store.mtime()

    def dispatch(events, current: datetime) -> None:
        nonlocal player
        for ev in events:
            if isinstance(ev, Fired):
                if player is not None:
                    player.stop()
                player = player_factory(ev.alarm.sound, engine.state.config)
                player.start()
                name = ev.alarm.label or ev.alarm.id
                notify_fn(
                    f"⏰ {name}",
                    "ringing — `alarm snooze` or `alarm dismiss` in any terminal",
                )
                if ev.alarm.open_url:
                    from .run import _open_url

                    _open_url(ev.alarm.open_url)
            elif isinstance(ev, Snoozed):
                if player is not None:
                    player.stop()
                    player = None
                if ev.auto:
                    name = ev.alarm.label or ev.alarm.id
                    notify_fn(f"⏰ {name}", f"auto-snoozed — rings again at {ev.until:%H:%M}")
            elif isinstance(ev, Dismissed):
                if player is not None:
                    player.stop()
                    player = None
            elif isinstance(ev, Missed):
                for alarm in ev.alarms:
                    print(f"MISSED: {alarm.label or alarm.id}", file=sys.stderr, flush=True)
            elif isinstance(ev, Dirty):
                save_merged(current)

    dispatch(engine.start(now), now)

    count = 0
    try:
        while iterations is None or count < iterations:
            count += 1
            now = now_fn()
            if clock_is_running():
                # a fullscreen clock owns ringing; go quiet and follow the file
                if player is not None:
                    player.stop()
                    player = None
                if engine.phase is Phase.RINGING:
                    engine.abort_ring(now)
                loaded_mtime = None  # force a reload once the clock exits
                sleep_fn(2.0)
                continue
            mtime = store.mtime()
            if mtime != loaded_mtime:
                fresh = store.load()
                if engine.phase is Phase.RINGING:
                    engine.state = fresh
                    if _ring_resolved_externally(engine, now):
                        if player is not None:
                            player.stop()
                            player = None
                        engine.abort_ring(now)
                else:
                    engine.state = fresh
                    engine.recompute(now)
                loaded_mtime = mtime
            events = engine.tick(now)
            dispatch(events, now)
            if player is not None:
                player.tick()
            sleep_fn(RING_TICK if engine.phase is Phase.RINGING else IDLE_TICK)
    finally:
        if player is not None:
            player.stop()
    return engine


# ------------------------------------------------------------- service files


def _daemon_argv(python: str) -> list[str]:
    return [python, "-m", "betteralarm", "daemon", "run"]


def launchd_plist(python: str) -> str:
    import os

    args = "\n".join(f"        <string>{a}</string>" for a in _daemon_argv(python))
    env_block = ""
    override = os.environ.get("BETTER_ALARM_HOME")
    if override:
        env_block = f"""
    <key>EnvironmentVariables</key>
    <dict>
        <key>BETTER_ALARM_HOME</key>
        <string>{override}</string>
    </dict>"""
    log = data_dir() / "daemon.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>{env_block}
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""


def systemd_unit(python: str) -> str:
    import os

    env_line = ""
    override = os.environ.get("BETTER_ALARM_HOME")
    if override:
        env_line = f"Environment=BETTER_ALARM_HOME={override}\n"
    return f"""[Unit]
Description=better-alarm background ringer

[Service]
ExecStart={python} -m betteralarm daemon run
Restart=always
RestartSec=2
{env_line}
[Install]
WantedBy=default.target
"""


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "better-alarm.service"


def _run_quiet(cmd: list[str]) -> int:
    try:
        return subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
    except OSError:
        return 1


def install() -> None:
    python = sys.executable
    if sys.platform == "darwin":
        path = _plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _run_quiet(["launchctl", "unload", str(path)])  # replace an old copy quietly
        path.write_text(launchd_plist(python))
        if _run_quiet(["launchctl", "load", "-w", str(path)]) != 0:
            raise UserError("launchctl load failed — check `launchctl list` and the plist")
        print(f"✔ background ringer installed (launchd: {LABEL})")
    elif sys.platform.startswith("linux"):
        path = _unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(python))
        _run_quiet(["systemctl", "--user", "daemon-reload"])
        if _run_quiet(["systemctl", "--user", "enable", "--now", "better-alarm"]) != 0:
            raise UserError("systemctl enable failed — is a user systemd session running?")
        print("✔ background ringer installed (systemd user unit: better-alarm)")
    else:
        raise UserError("daemon install isn't supported on this platform yet — keep `alarm run` open instead")
    print("  alarms now ring (sound + notification) with no terminal open")
    print("  control a ring from anywhere: `alarm snooze` · `alarm dismiss`")


def uninstall() -> None:
    if sys.platform == "darwin":
        path = _plist_path()
        _run_quiet(["launchctl", "unload", "-w", str(path)])
        path.unlink(missing_ok=True)
        print("✔ background ringer removed")
    elif sys.platform.startswith("linux"):
        _run_quiet(["systemctl", "--user", "disable", "--now", "better-alarm"])
        _unit_path().unlink(missing_ok=True)
        _run_quiet(["systemctl", "--user", "daemon-reload"])
        print("✔ background ringer removed")
    else:
        raise UserError("nothing to uninstall on this platform")


def is_running() -> bool:
    """Is the background ringer active? (quiet check, no output)"""
    if sys.platform == "darwin":
        return _run_quiet(["launchctl", "list", LABEL]) == 0
    if sys.platform.startswith("linux"):
        return _run_quiet(["systemctl", "--user", "is-active", "--quiet", "better-alarm"]) == 0
    return False


def status() -> int:
    if sys.platform == "darwin":
        installed = _plist_path().exists()
        running = is_running()
    elif sys.platform.startswith("linux"):
        installed = _unit_path().exists()
        running = is_running()
    else:
        print("daemon: not supported on this platform")
        return 1
    state = "running" if running else ("installed but not running" if installed else "not installed")
    print(f"background ringer: {state}")
    if not installed:
        print("  install it with `alarm daemon install` — alarms will ring with no terminal open")
    return 0 if running else 1
