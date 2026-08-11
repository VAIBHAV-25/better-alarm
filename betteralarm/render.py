"""Frame building (pure) and the renderers that paint frames to the terminal."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime

from . import bigfont, timeparse
from .models import Alarm
from .scheduler import next_alarm, next_ring
from .store import AppState

# Room the big clock needs beyond its own glyphs (borders, header, footer rows).
_BIG_MIN_HEIGHT = 14


def _in(delta) -> str:
    """'in 15h 41m', or plain 'now' — never 'in now'."""
    text = timeparse.format_delta(delta)
    return text if text == "now" else f"in {text}"


@dataclass
class Frame:
    """Everything on screen, as plain strings — computed pure, painted dumb."""

    clock: str
    date_line: str
    next_line: str
    alarm_rows: list[str]
    status: str
    ring_line: str | None
    big: bool
    progress: float | None = None  # 0..1 → a bar under the clock (timers)


def build_frame(
    state: AppState, now: datetime, ringing: Alarm | None, width: int, height: int
) -> Frame:
    cfg = state.config
    clock = timeparse.format_clock(now, cfg.time_format)

    if ringing is not None:
        ring_line = ringing.label or ringing.id
        snooze_m = ringing.snooze_minutes or cfg.snooze_minutes
        status = f"[s] snooze {snooze_m} min   ·   [1-9] snooze N min   ·   [d/enter] dismiss"
    else:
        ring_line = None
        status = "[q] quit   ·   manage alarms from another terminal: alarm add/list/rm"

    upcoming = next_alarm(state.alarms, now)
    if ringing is not None:
        next_line = f"unattended → auto-{cfg.auto_action} in {cfg.auto_action_minutes}m"
    elif upcoming is None:
        next_line = "no alarms scheduled"
    else:
        alarm, ring = upcoming
        clock_s = timeparse.format_clock(ring, cfg.time_format, seconds=False)
        next_line = f"next: {alarm.label or alarm.id} {_in(ring - now)} ({clock_s})"

    alarm_rows = []
    enabled = [a for a in state.alarms if a.enabled]
    for alarm in sorted(enabled, key=lambda a: next_ring(a, now) or datetime.max):
        ring = next_ring(alarm, now)
        due = _in(ring - now) if ring else "—"
        alarm_rows.append(
            f"{alarm.label or alarm.id:<12.12}  {alarm.describe_schedule(cfg.time_format):<20.20}  {due}"
        )

    big = width >= bigfont.width(clock) + 4 and height >= _BIG_MIN_HEIGHT
    date_line = now.strftime("%a %b") + f" {now.day}, {now.year}"
    return Frame(
        clock=clock,
        date_line=date_line,
        next_line=next_line,
        alarm_rows=alarm_rows[:6],
        status=status,
        ring_line=ring_line,
        big=big,
    )


class PlainRenderer:
    """Raw-ANSI fullscreen painter: alternate screen, hidden cursor, buffered repaints."""

    def __enter__(self) -> "PlainRenderer":
        sys.stdout.write("\x1b[?1049h\x1b[?25l")  # alt screen, hide cursor
        sys.stdout.flush()
        return self

    def __exit__(self, *exc) -> None:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")  # restore
        sys.stdout.flush()

    def size(self) -> tuple[int, int]:
        return shutil.get_terminal_size()

    def compose(self, frame: Frame, width: int, height: int) -> str:
        """The full screen as one string of `height` lines (pure, testable)."""

        def center(line: str) -> str:
            pad = max((width - len(line)) // 2, 0)
            return " " * pad + line

        lines: list[str] = [""]
        if frame.ring_line:
            inner = f"  ♪  RINGING — {frame.ring_line}  ♪  "
            lines += [
                center("╭" + "─" * len(inner) + "╮"),
                center("│" + inner + "│"),
                center("╰" + "─" * len(inner) + "╯"),
            ]
        if frame.big:
            lines += [center(row) for row in bigfont.render_big(frame.clock)]
        else:
            lines += [center(frame.clock)]
        lines += [center(frame.date_line)]
        if frame.progress is not None:
            filled = round(max(0.0, min(1.0, frame.progress)) * 30)
            bar = "▰" * filled + "▱" * (30 - filled)
            lines += ["", center(f"{bar}  {int(frame.progress * 100)}%")]
        lines += ["", center(frame.next_line)]
        if frame.alarm_rows and not frame.ring_line:
            lines += [""] + ["   " + row for row in frame.alarm_rows]
        while len(lines) < height - 1:
            lines.append("")
        lines = lines[: height - 1] + [center(frame.status)]
        return "\n".join(line[:width] for line in lines)

    # compose() puts the ring banner box on these screen rows
    _BANNER_ROWS = range(1, 4)

    def draw(self, frame: Frame) -> None:
        width, height = self.size()
        body = self.compose(frame, width, height).split("\n")
        painted = []
        for i, line in enumerate(body):
            # steady bold-yellow banner — never reverse video, never strobing
            if frame.ring_line and i in self._BANNER_ROWS:
                line = f"\x1b[1;33m{line}\x1b[0m"
            elif "█" in line:  # the big clock digits glow cyan
                line = f"\x1b[36m{line}\x1b[0m"
            elif "▰" in line or "▱" in line:  # progress bar
                line = f"\x1b[36m{line}\x1b[0m"
            # clear-to-EOL per line beats a full clear (no flicker)
            painted.append(f"\x1b[K{line}")
        sys.stdout.write("\x1b[H" + "\n".join(painted))
        sys.stdout.flush()


class LogRenderer:
    """Non-TTY / --plain: one line per state change, no ANSI."""

    def __init__(self) -> None:
        self._last: tuple | None = None

    def __enter__(self) -> "LogRenderer":
        return self

    def __exit__(self, *exc) -> None:
        pass

    def size(self) -> tuple[int, int]:
        return (80, 24)

    def draw(self, frame: Frame) -> None:
        key = (frame.ring_line, frame.next_line)
        if key == self._last:
            return
        self._last = key
        if frame.ring_line:
            print(f"{frame.clock} RINGING {frame.ring_line}")
        else:
            print(f"{frame.clock} {frame.next_line}")
        sys.stdout.flush()


def make_renderer(force_plain: bool = False):
    """Pick the best renderer for the situation: rich > raw ANSI > log lines."""
    # fullscreen needs BOTH ends: stdout for the UI, stdin for the keys —
    # a fullscreen screen advertising [q]/[s]/[d] with a dead keyboard is a trap
    if force_plain or not sys.stdout.isatty() or not sys.stdin.isatty():
        return LogRenderer()
    if importlib.util.find_spec("rich") is not None:
        from .render_rich import RichRenderer

        return RichRenderer()
    return PlainRenderer()
