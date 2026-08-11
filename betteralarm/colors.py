"""Minimal ANSI styling that vanishes when output isn't a real terminal.

Honors NO_COLOR (https://no-color.org) and FORCE_COLOR. Tests run with
captured output, so styled text degrades to plain automatically there.
"""

from __future__ import annotations

import os
import sys

_CODES = {
    "bold": "1",
    "dim": "2",
    "italic": "3",
    "underline": "4",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "gray": "90",
}


def enabled(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


def style(text: str, *names: str, when: bool | None = None) -> str:
    on = enabled() if when is None else when
    if not on or not names:
        return text
    seq = ";".join(_CODES[name] for name in names)
    return f"\x1b[{seq}m{text}\x1b[0m"
