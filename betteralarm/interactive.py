"""Shared prompt toolkit for conversational command flows.

Every primitive takes an injectable `input_fn` so flows are tested with
scripted answers, no real stdin. Ctrl-D (EOF) raises Cancelled anywhere,
which the CLI turns into a clean "cancelled" exit.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from typing import Callable

from . import timeparse
from .colors import enabled as colors_enabled
from .colors import style
from .store import AppState, find_alarm

try:  # arrows recall previous answers, left/right edit the line
    import readline  # noqa: F401

    HAS_READLINE = True
except ImportError:  # pragma: no cover
    HAS_READLINE = False

_SENTINEL = object()

# escape words: typing any of these at a prompt backs out, like Esc in a menu
_CANCEL_WORDS = ("back", "cancel", "esc")


class Cancelled(Exception):
    """The user backed out of a prompt (Ctrl-D, Esc, or typing 'back')."""


def is_interactive() -> bool:
    """Prompt only when a human is on both ends; scripts get errors, not hangs."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _rule() -> str:
    return style("─" * shutil.get_terminal_size().columns, "dim")


def _pointer() -> str:
    if not colors_enabled():
        return " ❯ "
    if HAS_READLINE:
        # \x01/\x02 tell readline the escape codes are zero-width, so line
        # editing and history recall don't garble the display
        return " \x01\x1b[1;36m\x02❯ \x01\x1b[0m\x02"
    return " " + style("❯ ", "cyan", "bold")


def input_line(title: str | None = None, *, input_fn: Callable[[str], str] | None = None) -> str:
    """One line of input between two full-width rules.

    EOF (Ctrl-D) raises Cancelled.
    """
    input_fn = input_fn or input  # resolve at call time so tests can patch builtins.input
    if title:
        print(title)
    print(_rule())
    try:
        raw = input_fn(_pointer()).strip()
    except EOFError:
        print()
        print(_rule())
        raise Cancelled from None
    print(_rule())
    return raw


def ask(
    question: str,
    *,
    default=_SENTINEL,
    parse: Callable[[str], object] | None = None,
    input_fn: Callable[[str], str] | None = None,
):
    """Ask until the answer parses. Empty input returns `default` unparsed."""
    hint = ""
    if default is not _SENTINEL and default not in (None, ""):
        hint = f" [{default}]"
    while True:
        raw = input_line(f"{question}{hint}", input_fn=input_fn)
        if raw.lower() in _CANCEL_WORDS:
            raise Cancelled
        if not raw:
            if default is not _SENTINEL:
                return default
            continue
        if parse is None:
            return raw
        try:
            return parse(raw)
        except ValueError as exc:
            print(style(f"  ✗ {exc}", "red"))


def _normalize_options(options) -> list[tuple[str, str]]:
    """Options are plain labels or (label, description) pairs."""
    return [(o, "") if isinstance(o, str) else (o[0], o[1]) for o in options]


def select(question: str, options, *, keys=None) -> int:
    """Arrow-key selector: ↑/↓ move the ❯ pointer, Enter picks, Esc cancels.

    Options may be strings or (label, description) tuples — descriptions
    render as a dim second column. `keys` injects a key stream for tests;
    without it, reads the real keyboard. A number key jumps to that option.
    """
    opts = _normalize_options(options)
    label_width = max(len(label) for label, _ in opts) + 4
    idx = 0

    def render(first: bool) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{len(opts)}A")
        for i, (label, desc) in enumerate(opts):
            if i == idx:
                head = style(f" ❯ {label.ljust(label_width)}", "cyan", "bold")
            else:
                head = f"   {label.ljust(label_width)}"
            line = head + (style(desc, "dim") if desc else "")
            sys.stdout.write("\r\x1b[2K" + line + "\n")
        sys.stdout.flush()

    def handle(key: str | None) -> int | None:
        nonlocal idx
        if key in ("esc", "q"):
            raise Cancelled
        if key == "enter":
            return idx
        if key == "up":
            idx = (idx - 1) % len(options)
        elif key == "down":
            idx = (idx + 1) % len(options)
        elif key and key.isdigit() and 1 <= int(key) <= len(options):
            return int(key) - 1
        return None

    print(question)
    print(style("   ↑/↓ move · Enter select · Esc cancel", "dim"))
    render(first=True)
    if keys is not None:
        for key in keys:
            done = handle(key)
            if done is not None:
                return done
            render(first=False)
        raise Cancelled
    from .keyboard import open_keyboard

    with open_keyboard() as kb:
        while True:
            key = kb.get_key(0.25, arrows=True)
            if key is None:
                continue
            done = handle(key)
            if done is not None:
                return done
            render(first=False)


def pick(
    question: str,
    options,
    *,
    input_fn: Callable[[str], str] | None = None,
) -> int:
    """Choose from a list: arrow-key selector on a real TTY, numbered otherwise.

    Options may be strings or (label, description) tuples.
    """
    # check the real streams, not is_interactive() — tests patch the latter but
    # feed answers through input(), which needs the numbered fallback
    if input_fn is None and sys.stdin.isatty() and sys.stdout.isatty():
        return select(question, options)
    input_fn = input_fn or input
    opts = _normalize_options(options)
    print(question)
    print(style("   (type a number, then Enter)", "dim"))
    for i, (label, desc) in enumerate(opts, 1):
        print(f"  {i}) {label}" + (f"  —  {desc}" if desc else ""))
    while True:
        try:
            raw = input_fn("> ").strip()
        except EOFError:
            raise Cancelled from None
        if raw.lower() in _CANCEL_WORDS:
            raise Cancelled
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  ✗ pick a number 1-{len(options)}")


def confirm(
    question: str,
    *,
    default: bool = False,
    input_fn: Callable[[str], str] | None = None,
) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input_line(f"{question} {hint}", input_fn=input_fn).lower()
        if raw in _CANCEL_WORDS:
            raise Cancelled
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(style("  ✗ y or n", "red"))


# ------------------------------------------------------- command flows
#
# Each flow fills the missing fields of an argparse Namespace with raw,
# already-validated strings, so the existing command handlers run unchanged.
# Flows also stash args._echo — the equivalent one-liner, printed after
# success to teach the fast path.


def _keep_raw(validate: Callable[[str], object]) -> Callable[[str], str]:
    """Wrap a parser so ask() validates the input but returns the raw text."""

    def parse(raw: str) -> str:
        validate(raw)
        return raw

    return parse


def _quoted(value: str) -> str:
    # quote anything that wouldn't survive a shell as one argument
    return shlex.quote(value) if value and " " in value else value


def describe_alarm(alarm, time_format: str) -> str:
    name = alarm.label or alarm.id
    suffix = "" if alarm.enabled else "  (off)"
    return f"{name} — {alarm.describe_schedule(time_format)}{suffix}"


def pick_alarm(question: str, state: AppState, cancel: str | None = None):
    """Pick an alarm from a list. With `cancel`, that option returns None."""
    options = [describe_alarm(a, state.config.time_format) for a in state.alarms]
    if cancel:
        options.append(cancel)
    choice = pick(question, options)
    if cancel and choice == len(state.alarms):
        return None
    return state.alarms[choice]


def _validate_time_or_when(raw: str) -> None:
    from datetime import datetime

    try:
        timeparse.parse_time(raw)
    except ValueError:
        timeparse.parse_when(raw, datetime.now())  # raises with its own examples


def add_prompts(args) -> None:
    """Ask for whatever `alarm add` is still missing (prefills are kept)."""
    if args.time is None:
        args.time = ask(
            "Time? (e.g. 7:30, 7pm, tomorrow 9am, monday 7pm)",
            parse=_keep_raw(_validate_time_or_when),
        )
    if not args.label:
        args.label = ask("Label?", default="")
    if args.repeat == "once":
        args.repeat = ask(
            "Repeat? (once, daily, weekdays, weekends, mon,wed,fri)",
            default="once",
            parse=_keep_raw(timeparse.parse_days),
        )
    echo = f"alarm add {args.time}"
    if args.label:
        echo += f" {_quoted(args.label)}"
    if args.repeat != "once":
        echo += f" --repeat {args.repeat}"
    args._echo = echo


def in_prompts(args) -> None:
    """Ask for whatever `alarm in` is still missing (prefills are kept)."""
    from datetime import datetime

    if args.duration is None:
        args.duration = ask(
            "How long from now? (e.g. 25m, 1h30m, 90s)", parse=_keep_raw(timeparse.parse_duration)
        )
    # the countdown starts NOW — a slow label answer must not push the ring later
    args._anchor = datetime.now()
    if not args.label:
        args.label = ask("Label?", default="")
    echo = f"alarm in {args.duration}"
    if args.label:
        echo += f" {_quoted(args.label)}"
    args._echo = echo


def _positive_minutes(raw: str) -> int:
    try:
        minutes = int(raw)
    except ValueError:
        raise ValueError(f"snooze wants a number of minutes, got {raw!r}") from None
    if minutes < 1:
        raise ValueError("snooze must be at least 1 minute")
    return minutes


def edit_prompts(args, state: AppState) -> bool:
    """Fill args for cmd_edit by asking. Returns False if there is nothing to do."""
    if not state.alarms:
        print("no alarms yet — just type `alarm` to set one up")
        return False
    if args.alarm is None:
        target = pick_alarm("Which alarm?", state, cancel="✕ cancel — go back")
        if target is None:
            print("cancelled — nothing changed")
            return False
        args.alarm = target.id
    else:
        target = find_alarm(state, args.alarm)

    tf = state.config.time_format
    fields = ("time", "label", "repeat", "sound", "snooze")
    pending: dict[str, str] = {}
    changes: list[tuple[str, str]] = []

    def current(field: str) -> str:
        if field in pending:
            return pending[field]
        if field == "time":
            return target.describe_schedule(tf).rsplit(" ", 1)[-1]
        if field == "label":
            return target.label or "—"
        if field == "repeat":
            schedule = target.describe_schedule(tf)
            return "once" if target.type == "once" else schedule.rsplit(" ", 1)[0]
        if field == "sound":
            return target.sound
        return f"{target.snooze_minutes or 'default'} min"

    while True:
        options = [f"{field.ljust(7)} ({current(field)})" for field in fields]
        options.append("✕ cancel — discard changes")
        choice = pick("What do you want to change?", options)
        if choice == len(fields):
            print("cancelled — nothing changed")
            return False
        field = fields[choice]
        if field == "time":
            raw = ask(
                "New time (e.g. 7:30, 7pm, tomorrow 9am, aug 20 14:00)",
                default="",
                parse=_keep_raw(_validate_time_or_when),
            )
        elif field == "label":
            raw = ask("New label", default="")
        elif field == "repeat":
            raw = ask(
                "Repeat? (once, daily, weekdays, weekends, mon,wed,fri)",
                default="",
                parse=_keep_raw(timeparse.parse_days),
            )
        elif field == "sound":
            raw = ask("Sound? (bell, system:NAME, file:/path, default)", default="")
        else:
            raw = ask("Snooze minutes", default="", parse=_positive_minutes)
        if raw != "" and raw is not None:
            setattr(args, field, raw)
            pending[field] = f"{raw} min" if field == "snooze" else str(raw)
            changes.append((f"--{field}", _quoted(str(raw))))
            print(f"  ✔ {field} → {raw}")
        else:
            print(f"  (kept {field} as it was)")
        if not confirm(f"change anything else on {target.label or target.id!r}?"):
            break
    if not changes:
        print("nothing changed")
        return False
    name = _quoted(target.label) if target.label else target.id
    args._echo = f"alarm edit {name} " + " ".join(f"{flag} {value}" for flag, value in changes)
    return True

