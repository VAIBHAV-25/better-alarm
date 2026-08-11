"""Desktop notifications: best-effort, never fatal, no dependencies.

A ring should reach the user even when the terminal is behind other windows.
macOS uses osascript, Linux uses notify-send; anywhere else this is a no-op.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def notification_command(title: str, message: str) -> list[str] | None:
    """The subprocess argv for a notification, or None if no backend exists."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        # json.dumps produces a double-quoted, escaped string — safe to embed
        # in AppleScript, so a label can't break out and run script code
        quote = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731
        script = f"display notification {quote(message)} with title {quote(title)}"
        return ["osascript", "-e", script]
    if shutil.which("notify-send"):
        return ["notify-send", title, message]
    return None


def notify(title: str, message: str) -> None:
    cmd = notification_command(title, message)
    if cmd is None:
        return
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass  # notifications are a bonus, never a crash
