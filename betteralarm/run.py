"""The live modes: `alarm run` dashboard, `alarm timer`, `alarm stopwatch`.

Single-threaded: the keyboard read timeout IS the tick (1 s idle, 0.25 s while
ringing). The engine decides what happened; this module does the side effects.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from typing import Callable

from .config import Config
from .engine import Dirty, Dismissed, Engine, Fired, Missed, Phase, Snoozed
from .keyboard import open_keyboard
from .models import Alarm, new_id
from .notify import notify
from .render import build_frame, make_renderer
from .sound import make_player
from .store import AppState, Store


def _open_url(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:
        pass  # a broken browser must not kill the ring

IDLE_TICK = 1.0
RING_TICK = 0.25


def run_dashboard(
    store: Store | None,
    *,
    force_plain: bool = False,
    state: AppState | None = None,
    quit_when_done: bool = False,
    keyboard=None,
    renderer=None,
    now_fn: Callable[[], datetime] | None = None,
    quit_rc: int = 0,
    skip_rc: int | None = None,
    footer: str | None = None,
    progress_fn: Callable[[datetime], float | None] | None = None,
) -> int:
    """Run the clock until the user quits (or, with quit_when_done, until idle+empty).

    quit_rc is returned when the user presses q — callers running a sequence
    of dashboards (pomodoro) use it to tell "user left" from "phase done".
    skip_rc, if set, is returned when the user presses n. footer overrides
    the idle status line so those keys can be advertised.
    """
    now_fn = now_fn or datetime.now
    if state is None:
        assert store is not None
        state = store.load()
    engine = Engine(state)
    renderer = renderer or make_renderer(force_plain)
    keyboard = keyboard or open_keyboard()

    startup_events = engine.start(now_fn())
    for ev in startup_events:
        if isinstance(ev, Missed):
            for alarm in ev.alarms:
                when = alarm.at.strftime("%b %d %H:%M") if alarm.at else "?"
                print(f"MISSED: {alarm.label or alarm.id} — was {when}", file=sys.stderr)

    player = None
    loaded_mtime = store.mtime() if store else None

    def save_merged(now: datetime) -> None:
        """Persist our changes without clobbering edits made from other terminals.

        If the file changed since we last read it, take the disk version as base
        (it has any external adds/removes/config edits) and overlay our in-memory
        alarm states (snoozes, dismissals) for alarms that still exist there.
        """
        nonlocal loaded_mtime
        assert store is not None
        if store.mtime() != loaded_mtime:
            disk = store.load()
            ours = {a.id: a for a in engine.state.alarms}
            disk.alarms = [ours.get(alarm.id, alarm) for alarm in disk.alarms]
            engine.state = disk
            engine.recompute(now)
        store.save(engine.state)
        loaded_mtime = store.mtime()

    def dispatch(events, now: datetime) -> None:
        nonlocal player
        for ev in events:
            if isinstance(ev, Fired):
                if player is not None:
                    player.stop()
                player = make_player(ev.alarm.sound, engine.state.config, insistent=True)
                player.start()
                if engine.state.config.notifications:
                    name = ev.alarm.label or ev.alarm.id
                    notify(f"⏰ {name}", "ringing — s snoozes · d dismisses")
                if ev.alarm.open_url:
                    _open_url(ev.alarm.open_url)
            elif isinstance(ev, (Snoozed, Dismissed)):
                if player is not None:
                    player.stop()
                    player = None
            elif isinstance(ev, Dirty) and store is not None:
                save_merged(now)

    from .daemon import clear_heartbeat, touch_heartbeat

    try:
        with renderer as r, keyboard as kb:
            dispatch(startup_events, now_fn())
            while True:
                if store is not None:
                    touch_heartbeat()  # tell a background daemon the clock owns rings
                tick = RING_TICK if engine.phase is Phase.RINGING else IDLE_TICK
                key = kb.get_key(tick)
                now = now_fn()
                if key == "q" and engine.phase is Phase.IDLE:
                    return quit_rc
                if key == "n" and skip_rc is not None and engine.phase is Phase.IDLE:
                    return skip_rc
                events = engine.handle_key(key, now) if key else []
                events += engine.tick(now)
                dispatch(events, now)
                if player is not None:
                    player.tick()
                if quit_when_done and engine.phase is Phase.IDLE and not engine.targets:
                    return 0
                if store is not None and engine.phase is Phase.IDLE:
                    mtime = store.mtime()
                    if mtime != loaded_mtime:
                        engine.state = store.load()
                        engine.recompute(now)
                        loaded_mtime = mtime
                width, height = r.size()
                frame = build_frame(engine.state, now, engine.ringing_alarm, width, height)
                if footer and engine.phase is Phase.IDLE:
                    frame.status = footer
                if progress_fn is not None:
                    frame.progress = progress_fn(now)
                r.draw(frame)
    except KeyboardInterrupt:
        return 130  # clean exit: context managers already restored the terminal
    finally:
        if store is not None:
            clear_heartbeat()
        if player is not None:
            player.stop()


def run_timer(
    duration: timedelta,
    label: str,
    *,
    force_plain: bool = False,
    keyboard=None,
    renderer=None,
    now_fn: Callable[[], datetime] | None = None,
    quit_rc: int = 0,
    skip_rc: int | None = None,
    footer: str | None = None,
) -> int:
    """Countdown timer: an ephemeral once-alarm on the dashboard, never persisted."""
    now = (now_fn or datetime.now)()
    config = Store().load().config  # respect user's sound/format settings
    alarm = Alarm(id=new_id(), label=label, type="once", at=now + duration)
    state = AppState(config=config, alarms=[alarm])

    def progress(t: datetime) -> float:
        return min(1.0, max(0.0, (t - now) / duration))

    return run_dashboard(
        None,
        force_plain=force_plain,
        state=state,
        quit_when_done=True,
        keyboard=keyboard,
        renderer=renderer,
        now_fn=now_fn,
        quit_rc=quit_rc,
        skip_rc=skip_rc,
        footer=footer,
        progress_fn=progress,
    )


def run_stopwatch() -> int:
    """Big ticking elapsed clock: [l] lap, [q] quit."""
    laps: list[float] = []
    start = time.monotonic()
    keyboard = open_keyboard()
    is_tty = sys.stdout.isatty()

    def fmt(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    print("stopwatch running — [l] lap, [q] quit", flush=True)
    try:
        with keyboard as kb:
            while True:
                key = kb.get_key(0.5 if is_tty else 1.0)
                elapsed = time.monotonic() - start
                if key == "q":
                    break
                if key == "l":
                    laps.append(elapsed)
                    sys.stdout.write(f"\rlap {len(laps)}: {fmt(elapsed)}\n")
                if is_tty:
                    sys.stdout.write(f"\r  {fmt(elapsed)} ")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    elapsed = time.monotonic() - start
    print(f"\rtotal: {fmt(elapsed)}" + (f" ({len(laps)} laps)" if laps else ""))
    return 0
