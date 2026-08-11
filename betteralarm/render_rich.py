"""Optional prettier renderer, used automatically when `rich` is installed.

Same Frame contract as PlainRenderer — this module is only imported after
render.make_renderer confirms rich is available.
"""

from __future__ import annotations

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from . import bigfont
from .render import Frame


class RichRenderer:
    def __enter__(self) -> "RichRenderer":
        self.console = Console()
        self.live = Live(console=self.console, screen=True, auto_refresh=False)
        self.live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.live.__exit__(*exc)

    def size(self) -> tuple[int, int]:
        size = self.console.size
        return (size.width, size.height)

    def draw(self, frame: Frame) -> None:
        parts = []
        if frame.ring_line:
            parts += [
                Text(),
                Align.center(Text(f"♪ RINGING — {frame.ring_line} ♪", style="bold yellow")),
            ]
        clock = "\n".join(bigfont.render_big(frame.clock)) if frame.big else frame.clock
        parts += [
            Text(),
            Align.center(Text(clock, style="bold cyan")),
            Align.center(Text(frame.date_line, style="dim")),
            Text(),
            Align.center(Text(frame.next_line, style="yellow" if frame.ring_line else "")),
        ]
        if frame.alarm_rows and not frame.ring_line:
            parts += [Text()] + [Align.center(Text(row, style="dim")) for row in frame.alarm_rows]
        panel = Panel(
            Group(*parts),
            subtitle=frame.status,
            subtitle_align="center",
            border_style="red" if frame.ring_line else "bright_black",
        )
        self.live.update(panel, refresh=True)
