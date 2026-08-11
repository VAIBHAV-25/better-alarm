"""Command-line entry point: argparse tree and thin command handlers."""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import fields
from datetime import datetime, timedelta

from . import interactive, timeparse
from .config import Config
from .errors import UserError
from .interactive import Cancelled
from .models import Alarm, new_id
from .scheduler import missed, next_alarm, next_ring
from .store import AppState, Store, find_alarm

COMMANDS = (
    "add", "in", "every", "list", "next", "remove", "rm", "edit", "enable", "disable",
    "skip", "pause", "resume", "run", "timer", "stopwatch", "pomodoro",
    "test-sound", "config", "import", "daemon", "snooze", "dismiss",
)

EPILOG = """\
examples, by goal:
  wake up on weekdays        alarm add 7:30 wake --repeat weekdays
  a specific day             alarm add "tomorrow 9am" gym · alarm add "aug 20 14:00"
  another timezone           alarm add 2pm call --tz Asia/Kolkata
  quick reminder             alarm in 25m tea
  recurring reminder         alarm every 30m water
  meeting that opens itself  alarm add 9:55 standup --open https://meet...
  ring with NO terminal      alarm daemon install   (then: alarm snooze / dismiss)
  the clock — alarms ring    alarm run
  while it is on screen
  see what's coming          alarm list · alarm next --json (scripts)
  change something           alarm edit          (it will ask you what)
  skip / vacation            alarm skip wake · alarm pause · alarm resume
  extras                     alarm timer 10m · alarm pomodoro · alarm import cal.ics

no arguments? just run `alarm` — it walks you through everything.
"""


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    if argv and not argv[0].startswith("-") and argv[0] not in COMMANDS:
        close = difflib.get_close_matches(argv[0], COMMANDS, n=1)
        hint = f" — did you mean {close[0]!r}?" if close else ""
        print(f"error: unknown command {argv[0]!r}{hint} (try `alarm --help`)", file=sys.stderr)
        return 2
    args = parser.parse_args(argv)
    if args.handler is None:
        if interactive.is_interactive():
            from .shell import run_shell

            return run_shell(parser)
        parser.print_usage(sys.stderr)
        return 2
    try:
        return args.handler(args)
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Cancelled:
        print("cancelled.")
        return 1
    except KeyboardInterrupt:
        print()
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm",
        description="A terminal alarm clock with a live dashboard.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(handler=None)
    sub = parser.add_subparsers(metavar="command")

    p = sub.add_parser("add", help="add an alarm (e.g. `alarm add 7:30 wake --repeat weekdays`)")
    p.add_argument("time", nargs="?", help="7:30, 0730, 7:30pm, ... (omit to be asked)")
    p.add_argument("label", nargs="?", default="")
    p.add_argument("--repeat", default="once", help="once, daily, weekdays, weekends, mon,wed,fri")
    p.add_argument("--sound", default="default", help="bell, system:NAME, file:/path, default")
    p.add_argument("--snooze", type=int, metavar="MIN", help="per-alarm snooze minutes")
    p.add_argument("--open", dest="open_url", metavar="URL", help="open this URL when it rings")
    p.add_argument("--tz", metavar="ZONE", help="interpret the time in this timezone (e.g. Asia/Kolkata)")
    p.add_argument("--disabled", action="store_true", help="create switched off")
    p.set_defaults(handler=cmd_add)

    p = sub.add_parser("in", help="one-shot alarm relative to now (e.g. `alarm in 25m tea`)")
    p.add_argument("duration", nargs="?", help="25m, 1h30m, 90s, or minutes (omit to be asked)")
    p.add_argument("label", nargs="?", default="")
    p.add_argument("--sound", default="default")
    p.set_defaults(handler=cmd_in)

    p = sub.add_parser("every", help="recurring interval (e.g. `alarm every 30m water`)")
    p.add_argument("duration", nargs="?", help="30m, 1h, 45s (omit to be asked)")
    p.add_argument("label", nargs="?", default="")
    p.add_argument("--sound", default="default")
    p.set_defaults(handler=cmd_every)

    p = sub.add_parser("skip", help="skip an alarm's next ring (keeps the schedule)")
    p.add_argument("alarm", metavar="ID_OR_LABEL", nargs="?")
    p.set_defaults(handler=cmd_skip)

    p = sub.add_parser("pause", help="switch all alarms off, remembering which")
    p.set_defaults(handler=cmd_pause)

    p = sub.add_parser("resume", help="switch back on everything `pause` turned off")
    p.set_defaults(handler=cmd_resume)

    p = sub.add_parser("pomodoro", help="work/break cycles (default 25/5x4)")
    p.add_argument("spec", nargs="?", help="e.g. 25/5x4 or 50/10x2")
    p.add_argument("--plain", action="store_true")
    p.set_defaults(handler=cmd_pomodoro)

    p = sub.add_parser("import", help="turn calendar events into alarms (`alarm import cal.ics`)")
    p.add_argument("file", help="path to an .ics file")
    p.add_argument("--before", type=int, default=0, metavar="MIN", help="ring N minutes early")
    p.set_defaults(handler=cmd_import)

    p = sub.add_parser("daemon", help="background ringer: alarms fire with no terminal open")
    p.add_argument(
        "action", nargs="?", default="status", choices=("install", "uninstall", "status", "run")
    )
    p.set_defaults(handler=cmd_daemon)

    p = sub.add_parser("snooze", help="snooze whatever is ringing right now")
    p.add_argument("minutes", nargs="?", type=int, help="defaults to your snooze setting")
    p.set_defaults(handler=cmd_snooze)

    p = sub.add_parser("dismiss", help="dismiss whatever is ringing right now")
    p.set_defaults(handler=cmd_dismiss)

    p = sub.add_parser("list", help="show alarms and their next ring times")
    p.add_argument("--all", action="store_true", help="include disabled alarms")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=cmd_list)

    p = sub.add_parser("next", help="show the next alarm (exit 1 if none)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=cmd_next)

    for name in ("remove", "rm"):
        p = sub.add_parser(name, help="remove an alarm by id or label" if name == "remove" else argparse.SUPPRESS)
        p.add_argument("alarm", metavar="ID_OR_LABEL", nargs="?")
        p.set_defaults(handler=cmd_remove)

    p = sub.add_parser("edit", help="change an alarm's time/label/repeat/sound/snooze")
    p.add_argument("alarm", metavar="ID_OR_LABEL", nargs="?")
    p.add_argument("--time")
    p.add_argument("--label")
    p.add_argument("--repeat")
    p.add_argument("--sound")
    p.add_argument("--snooze", type=int, metavar="MIN")
    p.set_defaults(handler=cmd_edit)

    for name, enabled in (("enable", True), ("disable", False)):
        p = sub.add_parser(name, help=f"{name} an alarm")
        p.add_argument("alarm", metavar="ID_OR_LABEL", nargs="?")
        p.set_defaults(handler=cmd_toggle, enabled=enabled)

    p = sub.add_parser("run", help="start the live clock (alarms ring here)")
    p.add_argument("--plain", action="store_true", help="line-per-event output, no fullscreen UI")
    p.set_defaults(handler=cmd_run)

    p = sub.add_parser("timer", help="countdown timer (e.g. `alarm timer 10m pasta`)")
    p.add_argument("duration")
    p.add_argument("label", nargs="?", default="timer")
    p.add_argument("--plain", action="store_true")
    p.set_defaults(handler=cmd_timer)

    p = sub.add_parser("stopwatch", help="big elapsed-time clock")
    p.set_defaults(handler=cmd_stopwatch)

    p = sub.add_parser("test-sound", help="preview a sound")
    p.add_argument("sound", nargs="?", default="default")
    p.set_defaults(handler=cmd_test_sound)

    p = sub.add_parser("config", help="show or change settings")
    csub = p.add_subparsers(metavar="action")
    p.set_defaults(handler=cmd_config_show)
    csub.add_parser("show").set_defaults(handler=cmd_config_show)
    g = csub.add_parser("get")
    g.add_argument("key")
    g.set_defaults(handler=cmd_config_get)
    s = csub.add_parser("set")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(handler=cmd_config_set)

    return parser


# ---------------------------------------------------------------- helpers


def _parse_or_user_error(fn, raw):
    try:
        return fn(raw)
    except ValueError as exc:
        raise UserError(str(exc)) from exc


def _check_snooze(minutes: int | None) -> None:
    if minutes is not None and minutes < 1:
        raise UserError("--snooze must be at least 1 minute")


def _announce(alarm: Alarm, state: AppState, now: datetime) -> str:
    ring = next_ring(alarm, now)
    when = f"rings in {timeparse.format_delta(ring - now)}" if ring else "currently off"
    label = f" {alarm.label!r}" if alarm.label else ""
    return (
        f"✔ alarm {alarm.id}{label} — {alarm.describe_schedule(state.config.time_format)} ({when})"
    )


def _print_echo(args) -> None:
    """After an interactive flow, teach the one-line version of what just happened."""
    echo = getattr(args, "_echo", None)
    if echo:
        print(f"※ next time, one line does this:  {echo}")


def _warn_needs_clock(args) -> None:
    """A human just set an alarm outside the shell: remind them what makes it ring.

    The shell handles this itself (it offers to start the clock), and scripts
    must stay clean, so this prints only for direct interactive use.
    """
    if interactive.is_interactive() and not getattr(args, "_in_shell", False):
        print("※ it rings only while the clock is on screen — start it with `alarm run`")


def _require_tty(hint: str) -> None:
    if not interactive.is_interactive():
        raise UserError(hint)


def _sweep_missed(state: AppState, now: datetime) -> list[str]:
    """Disable and report once-alarms that fired while nothing was running."""
    lines = []
    for alarm in missed(state.alarms, now):
        alarm.enabled = False
        alarm.last_dismissed = now
        when = alarm.at.strftime("%b %d %H:%M")
        lines.append(f"MISSED: {alarm.label or alarm.id} — was {when}")
    return lines


# ---------------------------------------------------------------- commands


def _parse_time_or_when(raw: str, now: datetime):
    """('tod', time) for wall-clock input, ('when', datetime) for a day+time phrase.

    Raises UserError with whichever message fits what the user seemed to mean.
    """
    try:
        return "tod", timeparse.parse_time(raw)
    except ValueError as time_error:
        try:
            return "when", timeparse.parse_when(raw, now)
        except ValueError as when_error:
            parts = raw.split()
            has_day_word = bool(parts) and any(c.isalpha() for c in parts[0])
            raise UserError(str(when_error if has_day_word else time_error)) from None


def _localize(dt: datetime, tz: str) -> datetime:
    """Interpret a naive local-looking datetime as wall time in `tz`; return local."""
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(tz)
    except Exception:
        raise UserError(
            f"unknown timezone {tz!r} — use Region/City, e.g. Asia/Kolkata, Europe/Berlin"
        ) from None
    return dt.replace(tzinfo=zone).astimezone().replace(tzinfo=None)


def cmd_add(args) -> int:
    if args.time is None:
        _require_tty("what time? e.g. `alarm add 7:30 wake` — or run `alarm add` in a terminal and it will ask")
        interactive.add_prompts(args)
    now = datetime.now()
    _check_snooze(args.snooze)
    tz = getattr(args, "tz", None)
    days = _parse_or_user_error(timeparse.parse_days, args.repeat)
    kind, parsed = _parse_time_or_when(args.time, now)
    if kind == "when":
        at = parsed
        if days:
            raise UserError("a specific date can't repeat — drop --repeat or use a plain time")
        if tz:
            at = _localize(at, tz)
            if at <= now:
                raise UserError(f"{args.time!r} in {tz} is already in the past here")
        alarm = Alarm(id=new_id(), label=args.label, type="once", at=at)
    else:
        when = parsed
        if tz:
            local = _localize(datetime.combine(now.date(), when), tz)
            when = local.time()
        if days:
            alarm = Alarm(id=new_id(), label=args.label, type="repeat", time=when, days=days)
        else:
            at = datetime.combine(now.date(), when)
            if at <= now:
                at += timedelta(days=1)
            alarm = Alarm(id=new_id(), label=args.label, type="once", at=at)
    alarm.sound = args.sound
    alarm.snooze_minutes = args.snooze
    alarm.open_url = getattr(args, "open_url", None)
    alarm.enabled = not args.disabled
    store = Store()
    state = store.load()
    state.alarms.append(alarm)
    store.save(state)
    print(_announce(alarm, state, now))
    _print_echo(args)
    _warn_needs_clock(args)
    return 0


def cmd_in(args) -> int:
    if args.duration is None:
        _require_tty("how long? e.g. `alarm in 25m tea` — or run `alarm in` in a terminal and it will ask")
        interactive.in_prompts(args)
    now = datetime.now()
    # prompts set an anchor when the duration was answered, so time spent
    # typing the label doesn't push the ring later
    base = getattr(args, "_anchor", None) or now
    duration = _parse_or_user_error(timeparse.parse_duration, args.duration)
    alarm = Alarm(
        id=new_id(), label=args.label, type="once", at=base + duration, sound=args.sound
    )
    store = Store()
    state = store.load()
    state.alarms.append(alarm)
    store.save(state)
    print(_announce(alarm, state, now))
    _print_echo(args)
    _warn_needs_clock(args)
    return 0


def cmd_every(args) -> int:
    if args.duration is None:
        _require_tty("how often? e.g. `alarm every 30m water`")
        args.duration = interactive.ask(
            "How often? (e.g. 30m, 1h)",
            parse=lambda raw: (timeparse.parse_duration(raw), raw)[1],
        )
        if not args.label:
            args.label = interactive.ask("Label?", default="")
    now = datetime.now()
    step = _parse_or_user_error(timeparse.parse_duration, args.duration)
    alarm = Alarm(
        id=new_id(),
        label=args.label,
        type="interval",
        interval_seconds=int(step.total_seconds()),
        sound=args.sound,
        created_at=now,
    )
    store = Store()
    state = store.load()
    state.alarms.append(alarm)
    store.save(state)
    print(_announce(alarm, state, now))
    _warn_needs_clock(args)
    return 0


def cmd_skip(args) -> int:
    now = datetime.now()
    store = Store()
    state = store.load()
    if args.alarm is None:
        _require_tty("which alarm? e.g. `alarm skip wake`")
        if not state.alarms:
            print("no alarms to skip")
            return 0
        alarm = interactive.pick_alarm(
            "Skip which alarm's next ring?", state, cancel="✕ cancel — go back"
        )
        if alarm is None:
            print("cancelled — nothing skipped")
            return 0
    else:
        alarm = find_alarm(state, args.alarm)
    if alarm.type == "once":
        alarm.enabled = False
        store.save(state)
        print(f"skipped {alarm.label or alarm.id!r} — it was a one-shot, so it's now off")
        return 0
    ring = next_ring(alarm, now)
    if ring is None:
        print(f"{alarm.label or alarm.id!r} has nothing coming up to skip")
        return 0
    alarm.skip_until = ring
    alarm.snooze_until = None
    store.save(state)
    following = next_ring(alarm, now)
    when = f"; next ring {timeparse.format_delta(following - now)} from now" if following else ""
    print(f"skipping {alarm.label or alarm.id!r} at {ring.strftime('%b %d %H:%M')}{when}")
    return 0


def cmd_pause(args) -> int:
    store = Store()
    state = store.load()
    paused = [a for a in state.alarms if a.enabled]
    if not paused:
        print("nothing to pause — no enabled alarms")
        return 0
    for alarm in paused:
        alarm.enabled = False
    state.config.paused_ids = [a.id for a in paused]
    store.save(state)
    print(f"paused {len(paused)} alarm{'s' if len(paused) != 1 else ''} — `alarm resume` brings them back")
    return 0


def cmd_resume(args) -> int:
    store = Store()
    state = store.load()
    ids = set(state.config.paused_ids)
    resumed = 0
    for alarm in state.alarms:
        if alarm.id in ids:
            alarm.enabled = True
            resumed += 1
    state.config.paused_ids = []
    store.save(state)
    if resumed:
        print(f"resumed {resumed} alarm{'s' if resumed != 1 else ''}")
    else:
        print("nothing was paused")
    return 0


def parse_pomodoro(spec: str | None) -> list[tuple[str, timedelta]]:
    """'25/5x4' → alternating work/break phases, no break after the last round."""
    import re as _re

    spec = spec or "25/5x4"
    m = _re.fullmatch(r"(\d+)\s*/\s*(\d+)(?:\s*x\s*(\d+))?", spec.strip())
    if not m:
        raise ValueError(f"can't parse pomodoro spec {spec!r}; try 25/5x4 (work/break x rounds)")
    work, rest, rounds = int(m.group(1)), int(m.group(2)), int(m.group(3) or 4)
    if not work or not rounds:
        raise ValueError("work minutes and rounds must be positive")
    phases: list[tuple[str, timedelta]] = []
    for i in range(1, rounds + 1):
        phases.append((f"work {i}/{rounds}", timedelta(minutes=work)))
        if i < rounds and rest:
            phases.append(("break", timedelta(minutes=rest)))
    return phases


# distinct exit codes so the pomodoro loop can tell "user left" from "phase done"
_POMO_STOP = 3
_POMO_SKIP = 4


def _pomodoro_footer(done: int, total: int, label: str) -> str:
    """Round tracker: 🍅 per finished round, · for the rest."""
    tomatoes = "🍅" * done + "·" * (total - done)
    return f"{tomatoes}  {label}   ·   [n] skip this phase   ·   [q] stop the pomodoro"


def _run_timer_phase(duration: timedelta, label: str, plain: bool = False, footer: str | None = None) -> int:
    from .run import run_timer

    return run_timer(
        duration,
        label,
        force_plain=plain,
        quit_rc=_POMO_STOP,
        skip_rc=_POMO_SKIP,
        footer=footer or "[n] skip this phase   ·   [q] stop the pomodoro",
    )


def cmd_pomodoro(args) -> int:
    phases = _parse_or_user_error(parse_pomodoro, args.spec)
    total = sum(1 for label, _ in phases if label.startswith("work"))
    done = 0
    for label, duration in phases:
        footer = _pomodoro_footer(done, total, label)
        rc = _run_timer_phase(duration, label, getattr(args, "plain", False), footer)
        if rc == _POMO_STOP:
            print("pomodoro stopped — see you next time")
            return 0
        if label.startswith("work") and rc != _POMO_SKIP:
            done += 1
        if rc == _POMO_SKIP:
            continue
        if rc != 0:
            return rc
    print(f"pomodoro done — {'🍅' * total} nice work 🎉")
    return 0


# countdown urgency: red when imminent, yellow within the hour
def _countdown_style(delta: timedelta) -> str | None:
    if delta <= timedelta(minutes=10):
        return "red"
    if delta <= timedelta(hours=1):
        return "yellow"
    return None


def cmd_import(args) -> int:
    from .ics import parse_ics

    now = datetime.now()
    try:
        text = open(args.file, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        raise UserError(f"can't read {args.file}: {exc}") from None
    store = Store()
    state = store.load()
    created = 0
    for summary, start in parse_ics(text, now):
        at = start - timedelta(minutes=args.before)
        if at <= now:
            continue
        state.alarms.append(Alarm(id=new_id(), label=summary, type="once", at=at))
        created += 1
    if created:
        store.save(state)
    early = f" ({args.before} min early)" if args.before else ""
    print(f"imported {created} alarm{'s' if created != 1 else ''} from {args.file}{early}")
    return 0


def cmd_daemon(args) -> int:
    from . import daemon

    if args.action == "install":
        daemon.install()
        return 0
    if args.action == "uninstall":
        daemon.uninstall()
        return 0
    if args.action == "run":
        # stdout is a log file under launchd/systemd: flush so lines land promptly
        print("better-alarm daemon: watching for alarms (Ctrl-C to stop)", flush=True)
        try:
            daemon.daemon_loop(Store())
        except KeyboardInterrupt:
            pass
        return 0
    return daemon.status()


def _due_right_now(state, now: datetime):
    """The alarm a daemon (or clock) would be ringing at this moment, if any."""
    from .scheduler import last_due

    candidates = [(due, a) for a in state.alarms if (due := last_due(a, now)) is not None]
    if not candidates:
        return None
    return min(candidates)[1]


def cmd_snooze(args) -> int:
    now = datetime.now()
    store = Store()
    state = store.load()
    alarm = _due_right_now(state, now)
    if alarm is None:
        print("nothing is ringing right now")
        return 1
    minutes = args.minutes or alarm.snooze_minutes or state.config.snooze_minutes
    if minutes < 1:
        raise UserError("snooze must be at least 1 minute")
    alarm.snooze_until = now + timedelta(minutes=minutes)
    store.save(state)
    print(f"snoozed {alarm.label or alarm.id!r} for {minutes} min (rings {alarm.snooze_until:%H:%M})")
    return 0


def cmd_dismiss(args) -> int:
    now = datetime.now()
    store = Store()
    state = store.load()
    alarm = _due_right_now(state, now)
    if alarm is None:
        print("nothing is ringing right now")
        return 1
    alarm.snooze_until = None
    alarm.last_dismissed = now
    if alarm.type == "once":
        alarm.enabled = False
    store.save(state)
    print(f"dismissed {alarm.label or alarm.id!r}")
    return 0


def cmd_list(args) -> int:
    now = datetime.now()
    store = Store()
    state = store.load()
    swept = _sweep_missed(state, now)
    as_json = getattr(args, "json", False)
    if not as_json:
        for line in swept:
            print(line)
    if swept:
        store.save(state)

    visible = [a for a in state.alarms if a.enabled or args.all]
    if as_json:
        import json as _json

        rows = []
        for alarm in sorted(visible, key=lambda a: next_ring(a, now) or datetime.max):
            ring = next_ring(alarm, now)
            rows.append(
                {
                    "id": alarm.id,
                    "label": alarm.label,
                    "type": alarm.type,
                    "enabled": alarm.enabled,
                    "schedule": alarm.describe_schedule(state.config.time_format),
                    "sound": alarm.sound,
                    "next_ring": ring.isoformat() if ring else None,
                    "snoozed": bool(alarm.snooze_until and ring == alarm.snooze_until),
                }
            )
        print(_json.dumps(rows, indent=2))
        return 0
    if not visible:
        print(
            "no alarms yet — just type `alarm` for a guided setup, "
            "or `alarm add 7:30 wake --repeat weekdays`"
        )
        return 0

    from .colors import style

    rows = []
    for alarm in sorted(visible, key=lambda a: next_ring(a, now) or datetime.max):
        ring = next_ring(alarm, now)
        if ring is None:
            nxt = "— off" if not alarm.enabled else "—"
        elif alarm.snooze_until and ring == alarm.snooze_until:
            nxt = f"snoozed, in {timeparse.format_delta(ring - now)}"
        else:
            nxt = f"in {timeparse.format_delta(ring - now)}"
            urgency = _countdown_style(ring - now)
            if urgency:
                nxt = style(nxt, urgency, "bold")
        rows.append(
            (
                alarm.id,
                alarm.label or "-",
                alarm.describe_schedule(state.config.time_format),
                alarm.sound,
                nxt,
            )
        )
    headers = ("ID", "LABEL", "SCHEDULE", "SOUND", "NEXT RING")
    widths = [max(len(r[i]) for r in rows + [headers]) for i in range(len(headers))]
    for row in [headers, *rows]:
        print("  ".join(str(cell).ljust(w) for cell, w in zip(row, widths)).rstrip())
    return 0


def cmd_next(args) -> int:
    now = datetime.now()
    store = Store()
    state = store.load()
    swept = _sweep_missed(state, now)
    as_json = getattr(args, "json", False)
    if not as_json:
        for line in swept:
            print(line)
    if swept:
        store.save(state)
    found = next_alarm(state.alarms, now)
    if as_json:
        import json as _json

        if not found:
            print("null")
            return 1
        alarm, ring = found
        print(
            _json.dumps(
                {
                    "id": alarm.id,
                    "label": alarm.label,
                    "at": ring.isoformat(),
                    "in_seconds": int((ring - now).total_seconds()),
                }
            )
        )
        return 0
    if not found:
        print("no upcoming alarms")
        return 1
    alarm, ring = found
    clock = timeparse.format_clock(ring, state.config.time_format, seconds=False)
    print(f"{alarm.label or alarm.id} rings in {timeparse.format_delta(ring - now)} ({clock})")
    return 0


def cmd_remove(args) -> int:
    store = Store()
    state = store.load()
    if args.alarm is None:
        _require_tty("which alarm? e.g. `alarm remove wake` (see `alarm list`)")
        if not state.alarms:
            print("no alarms to remove")
            return 0
        options = [
            interactive.describe_alarm(a, state.config.time_format) for a in state.alarms
        ] + ["✕ cancel — keep everything"]
        choice = interactive.pick("Remove which alarm?", options)
        if choice == len(state.alarms):
            print("cancelled — nothing removed")
            return 0
        alarm = state.alarms[choice]
        if not interactive.confirm(
            f"remove {alarm.label or alarm.id!r} — {alarm.describe_schedule(state.config.time_format)}?"
        ):
            print("kept it")
            return 0
    else:
        alarm = find_alarm(state, args.alarm)
    state.alarms.remove(alarm)
    store.save(state)
    print(f"removed {alarm.id} {alarm.label!r}")
    return 0


def cmd_edit(args) -> int:
    _check_snooze(args.snooze)
    store = Store()
    state = store.load()
    no_flags = all(
        getattr(args, name) is None for name in ("time", "label", "repeat", "sound", "snooze")
    )
    if args.alarm is None or no_flags:
        _require_tty(
            "nothing to change — e.g. `alarm edit wake --time 8:00`, "
            "or run `alarm edit` in a terminal and it will ask"
        )
        if not interactive.edit_prompts(args, state):
            return 0
    alarm = find_alarm(state, args.alarm)
    if args.time is not None or args.repeat is not None:
        alarm.snooze_until = None  # rescheduling supersedes a pending snooze
    if args.time is not None:
        now = datetime.now()
        kind, parsed = _parse_time_or_when(args.time, now)
        if kind == "when":
            # a concrete date: the alarm becomes a one-shot at that moment
            if args.repeat is not None and _parse_or_user_error(timeparse.parse_days, args.repeat):
                raise UserError("a specific date can't repeat — drop --repeat or use a plain time")
            alarm.type, alarm.at = "once", parsed
            alarm.time, alarm.days = None, ()
            args.repeat = None  # nothing left for the repeat block to do
        elif alarm.type == "once":
            at = datetime.combine(now.date(), parsed)
            alarm.at = at if at > now else at + timedelta(days=1)
        else:
            alarm.time = parsed
    if args.repeat is not None:
        days = _parse_or_user_error(timeparse.parse_days, args.repeat)
        if days:
            base_time = alarm.time or (alarm.at.time() if alarm.at else None)
            alarm.type, alarm.time, alarm.days, alarm.at = "repeat", base_time, days, None
        elif alarm.type == "repeat":  # already-once + --repeat once is a no-op
            now = datetime.now()
            at = datetime.combine(now.date(), alarm.time)
            alarm.type = "once"
            alarm.at = at if at > now else at + timedelta(days=1)
            alarm.time, alarm.days = None, ()
    if args.label is not None:
        alarm.label = args.label
    if args.sound is not None:
        alarm.sound = args.sound
    if args.snooze is not None:
        alarm.snooze_minutes = args.snooze
    store.save(state)
    print(_announce(alarm, state, datetime.now()))
    _print_echo(args)
    return 0


def cmd_toggle(args) -> int:
    store = Store()
    state = store.load()
    verb = "enable" if args.enabled else "disable"
    if args.alarm is None:
        _require_tty(f"which alarm? e.g. `alarm {verb} wake` (see `alarm list --all`)")
        if not state.alarms:
            print(f"no alarms to {verb}")
            return 0
        alarm = interactive.pick_alarm(
            f"{verb.capitalize()} which alarm?", state, cancel="✕ cancel — go back"
        )
        if alarm is None:
            print("cancelled — nothing changed")
            return 0
    else:
        alarm = find_alarm(state, args.alarm)
    alarm.enabled = args.enabled
    if not args.enabled:
        alarm.snooze_until = None
    store.save(state)
    print(_announce(alarm, state, datetime.now()))
    return 0


def cmd_config_show(args) -> int:
    config = Store().load().config
    for key, value in config.to_dict().items():
        print(f"{key} = {value}")
    return 0


def cmd_config_get(args) -> int:
    config = Store().load().config
    if not hasattr(config, args.key):
        raise UserError(f"unknown config key {args.key!r}")
    print(getattr(config, args.key))
    return 0


_CONFIG_VALIDATORS = {
    "time_format": lambda v: v in ("12", "24"),
    "auto_action": lambda v: v in ("snooze", "dismiss"),
}

# 0-minute snoozes refire instantly; a 0-minute auto-action dismisses on the first tick
_CONFIG_MINIMUMS = {"snooze_minutes": 1, "auto_action_minutes": 1, "max_auto_snoozes": 0}


def _coerce_config_value(config: Config, key: str, raw: str):
    """Turn raw text into a valid value for `key`, or raise UserError."""
    if not hasattr(config, key):
        raise UserError(f"unknown config key {key!r}; see `alarm config show`")
    current = getattr(config, key)
    if isinstance(current, bool):
        if raw.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            raise UserError(f"{key} wants true/false, got {raw!r}")
        value = raw.lower() in ("true", "1", "yes", "on")
    elif isinstance(current, int):
        try:
            value = int(raw)
        except ValueError:
            raise UserError(f"{key} wants a number, got {raw!r}") from None
        minimum = _CONFIG_MINIMUMS.get(key, 0)
        if value < minimum:
            raise UserError(f"{key} must be >= {minimum}")
    else:
        value = raw
    check = _CONFIG_VALIDATORS.get(key)
    if check and not check(str(value)):
        raise UserError(f"invalid value {raw!r} for {key}")
    return value


def cmd_config_set(args) -> int:
    store = Store()
    state = store.load()
    if args.key is None:
        _require_tty("usage: alarm config set KEY VALUE (see `alarm config show`)")
        names = [f.name for f in fields(Config)]
        choice = interactive.pick(
            "Which setting?", [f"{n} = {getattr(state.config, n)}" for n in names]
        )
        args.key = names[choice]
    if args.value is None:
        _require_tty(f"usage: alarm config set {args.key} VALUE")

        def parse(raw):
            try:
                return _coerce_config_value(state.config, args.key, raw)
            except UserError as exc:
                raise ValueError(str(exc)) from None

        value = interactive.ask(
            f"New value for {args.key}", default=getattr(state.config, args.key), parse=parse
        )
    else:
        value = _coerce_config_value(state.config, args.key, args.value)
    setattr(state.config, args.key, value)
    store.save(state)
    print(f"{args.key} = {value}")
    return 0




# Deferred imports keep management commands snappy and avoid importing terminal
# machinery (and its platform modules) unless actually running the clock.


def cmd_run(args) -> int:
    from .run import run_dashboard

    return run_dashboard(Store(), force_plain=args.plain)


def cmd_timer(args) -> int:
    from .run import run_timer

    duration = _parse_or_user_error(timeparse.parse_duration, args.duration)
    return run_timer(duration, args.label, force_plain=args.plain)


def cmd_stopwatch(args) -> int:
    from .run import run_stopwatch

    return run_stopwatch()


def cmd_test_sound(args) -> int:
    from .sound import test_sound

    return test_sound(args.sound, Store().load().config)
