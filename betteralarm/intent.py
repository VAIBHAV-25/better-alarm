"""Plain-English input → an Intent the shell can act on. Pure text, no IO.

Deliberately forgiving: every extracted value is offered back through the
normal prompt flow (shown as a default the user can override), so a wrong
guess costs one keystroke, never a wrong alarm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Intent:
    action: str
    time: str | None = None
    duration: str | None = None
    label: str | None = None


_SLASH = {
    "add": "add", "alarm": "add",
    "in": "in", "remind": "in", "reminder": "in",
    "list": "list", "ls": "list",
    "next": "next",
    "edit": "edit",
    "remove": "remove", "rm": "remove", "delete": "remove",
    "enable": "enable", "disable": "disable",
    "run": "run", "clock": "run", "start": "run",
    "timer": "timer", "stopwatch": "stopwatch",
    "settings": "settings", "config": "settings",
    "sound": "sound", "test-sound": "sound",
    "every": "every", "skip": "skip", "pause": "pause", "resume": "resume",
    "pomodoro": "pomodoro",
    "daemon": "daemon", "dismiss": "dismiss", "snooze": "snooze",
    "menu": "menu",
    "help": "help",
    "quit": "quit", "exit": "quit",
}

_UNIT = {
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "m": "m", "min": "m", "mins": "m", "minute": "m", "minutes": "m",
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
}

_DUR_WORDS = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b"
)
_TIME = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|\d{3,4})\b")

_DAY_WORDS = (
    "today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    "|mon|tues?|wed|thur?s?|fri|sat|sun"
)
# a day word followed by a time ("tomorrow at 9am", "monday 7:30", "tomorrow 9")
_WHEN = re.compile(
    rf"\b(?P<day>{_DAY_WORDS})\s+(?:at\s+)?"
    rf"(?P<time>\d{{1,2}}:\d{{2}}\s*(?:am|pm)?|\d{{1,2}}\s*(?:am|pm)|\d{{3,4}}|\d{{1,2}})\b"
)


def _extract_when(text: str) -> str | None:
    m = _WHEN.search(text)
    if not m:
        return None
    # (kept out of the f-string: backslashes there need Python >= 3.12)
    when_time = re.sub(r"\s+", "", m.group("time"))
    return f"{m.group('day')} {when_time}"


def _extract_duration(text: str) -> tuple[str | None, str]:
    """Pull '25 minutes' / '1h30m' out of the text; return (normalized, rest)."""
    parts, spans = [], []
    for m in _DUR_WORDS.finditer(text):
        parts.append(f"{m.group(1)}{_UNIT[m.group(2)]}")
        spans.append(m.span())
    if not parts:
        return None, text
    pieces, last = [], 0
    for start, end in spans:
        pieces.append(text[last:start])
        last = end
    pieces.append(text[last:])
    return "".join(parts), "".join(pieces)


def _extract_time(text: str) -> str | None:
    m = _TIME.search(text)
    return re.sub(r"\s+", "", m.group(1)) if m else None


def _extract_label(rest: str) -> str | None:
    rest = re.sub(r"\bremind(\s+me)?\b", "", rest)
    m = re.search(r"\bto\s+(.+)$", rest)
    if not m:
        return None
    label = m.group(1).strip()
    label = re.sub(r"\s*\b(in|at|me|please)\b\s*$", "", label).strip(" ,.!")
    return label or None


def parse_intent(text: str) -> Intent:
    low = " ".join(text.strip().lower().split())
    if not low:
        return Intent("unknown")

    if low.startswith("/"):
        head, _, rest = low[1:].partition(" ")
        if not head:
            return Intent("commands")  # bare "/" asks what commands exist
        # a typo'd command gets the palette, not a shrug
        intent = Intent(_SLASH.get(head, "commands"))
        if rest:
            intent.duration, _ = _extract_duration(rest)
            intent.time = _extract_time(rest)
        return intent

    words = set(re.findall(r"[a-z']+", low))
    if low == "menu":
        return Intent("menu")
    if low in ("q", "bye") or {"quit", "exit", "bye"} & words:
        return Intent("quit")
    if low == "?" or "help" in words or "what can you do" in low:
        return Intent("help")
    if "stopwatch" in words:
        return Intent("stopwatch")
    if "pomodoro" in words:
        return Intent("pomodoro")
    if "timer" in words:
        duration, _ = _extract_duration(low)
        return Intent("timer", duration=duration)
    if "skip" in words:
        return Intent("skip")
    if "daemon" in words or "background" in words:
        return Intent("daemon")
    if "dismiss" in words:
        return Intent("dismiss")
    if "snooze" in words:
        return Intent("snooze")
    if "pause" in words:
        return Intent("pause")
    if {"resume", "unpause"} & words:
        return Intent("resume")
    if "every" in words:
        duration, rest = _extract_duration(low)
        if duration:
            return Intent("every", duration=duration, label=_extract_label(rest))
    if {"remove", "delete", "cancel"} & words:
        return Intent("remove")
    if {"edit", "change", "update", "reschedule", "rename", "modify"} & words:
        return Intent("edit")
    if "disable" in words or "turn off" in low:
        return Intent("disable")
    if "enable" in words or "turn on" in low:
        return Intent("enable")
    if {"settings", "setting", "config", "preferences", "options"} & words:
        return Intent("settings")
    if {"list", "show"} & words or ("alarms" in words and {"what", "my"} & words):
        return Intent("list")
    if "next" in words:
        return Intent("next")
    if "clock" in words or low in ("run", "start"):
        return Intent("run")

    when_phrase = _extract_when(low)
    if when_phrase:
        return Intent("add", time=when_phrase, label=_extract_label(low))

    duration, rest = _extract_duration(low)
    wants_alarm = {"wake", "alarm", "set", "add", "new", "create"} & words
    if {"remind", "reminder", "remember"} & words or (duration and not wants_alarm):
        return Intent("in", duration=duration, label=_extract_label(rest))

    when = _extract_time(low)
    if wants_alarm or (when and _TIME.fullmatch(low)):
        return Intent("add", time=when)
    return Intent("unknown")
