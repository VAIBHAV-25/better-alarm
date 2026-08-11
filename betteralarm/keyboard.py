"""Single-key non-blocking input, cross-platform, always restoring the terminal.

POSIX uses cbreak (not raw) so Ctrl-C still delivers SIGINT; Windows uses msvcrt;
non-TTY stdin gets a Null keyboard whose get_key is just a sleep. The get_key
timeout doubles as the run loop's tick timer.
"""

from __future__ import annotations

import os
import sys
import time


def normalize(ch: str) -> str | None:
    """Map a raw character to a key name; None for keys we ignore."""
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch in ("\r", "\n"):
        return "enter"
    if ch.isprintable() and ch != " ":
        return ch.lower()
    return None


class NullKeyboard:
    """Stdin isn't a TTY: no keys, just pacing."""

    def __enter__(self) -> "NullKeyboard":
        return self

    def __exit__(self, *exc) -> None:
        pass

    def get_key(self, timeout: float, arrows: bool = False) -> str | None:
        time.sleep(timeout)
        return None


class PosixKeyboard:
    def __enter__(self) -> "PosixKeyboard":
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc) -> None:
        import termios

        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    def _wait_readable(self, timeout: float) -> bool:
        import select

        return bool(select.select([self._fd], [], [], timeout)[0])

    def _read_char(self) -> str:
        return os.read(self._fd, 1).decode(errors="ignore")

    def get_key(self, timeout: float, arrows: bool = False) -> str | None:
        if not self._wait_readable(timeout):
            return None
        ch = self._read_char()
        if ch == "\x1b":
            if arrows:
                # decode CSI arrows; a lone ESC (nothing follows) is "esc"
                if not self._wait_readable(0.05):
                    return "esc"
                if self._read_char() == "[" and self._wait_readable(0.05):
                    final = self._read_char()
                    return {"A": "up", "B": "down"}.get(final)
                return None
            # Swallow the rest of an escape sequence (arrows etc.). The tail bytes
            # may still be in flight over SSH, so poll briefly instead of only
            # instantaneously — a leaked '[D' would look like a 'd' (dismiss!).
            quiet_polls = 0
            while quiet_polls < 2:
                if self._wait_readable(0.025):
                    self._read_char()
                    quiet_polls = 0
                else:
                    quiet_polls += 1
            return None
        return normalize(ch)


class WindowsKeyboard:
    def __enter__(self) -> "WindowsKeyboard":
        return self

    def __exit__(self, *exc) -> None:
        pass

    def get_key(self, timeout: float, arrows: bool = False) -> str | None:
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # function/arrow prefix pair
                    tail = msvcrt.getwch()
                    if arrows:
                        return {"H": "up", "P": "down"}.get(tail)
                    continue
                if arrows and ch == "\x1b":
                    return "esc"
                return normalize(ch)
            time.sleep(0.02)
        return None


def open_keyboard():
    if not sys.stdin.isatty():
        return NullKeyboard()
    if os.name == "nt":
        return WindowsKeyboard()
    return PosixKeyboard()
