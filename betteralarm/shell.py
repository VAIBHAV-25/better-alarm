"""The interactive shell behind bare `alarm`: a conversational REPL.

A welcome banner, then a `❯` prompt that accepts plain English ("wake me at
7:30", "remind me in 20 minutes to stretch"), slash commands (/list), or an
empty Enter for an arrow-key menu. Every flow ends back at the prompt.
Styling degrades to plain text off-TTY (and under NO_COLOR).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import interactive, timeparse, tips
from .colors import style
from .config import data_path
from .errors import UserError
from .intent import Intent, parse_intent
from .interactive import Cancelled
from .scheduler import next_alarm, next_ring
from .store import Store

# (label, what-it-does, action) — labels carry an icon, descriptions say
# what happens in plain words, so the menu explains itself
MENU = (
    ("⏰ Set an alarm", "at a time — once, repeating, or 'tomorrow 9am'", "add"),
    ("⏳ Quick reminder", '"in 20 minutes" — tea, laundry, a break', "in"),
    ("🔁 Recurring reminder", "every 30 minutes — water, stretching", "every"),
    ("🔔 Start the clock", "THE screen where alarms ring", "run"),
    ("📋 List alarms", "everything scheduled, with countdowns", "list"),
    ("📝 Edit an alarm", "change its time, label, repeat, or sound", "edit"),
    ("⏩ Skip a ring", "skip an alarm's next ring, keep the schedule", "skip"),
    ("🌴 Pause / resume all", "vacation mode: everything off, then back", "pausetoggle"),
    ("❌ Remove an alarm", "delete one — asks before it does", "remove"),
    ("⏲  Timer", "countdown right now — pasta, laundry", "timer"),
    ("⏱  Stopwatch", "big elapsed clock, [l] records laps", "stopwatch"),
    ("🍅 Pomodoro", "25/5 work-break cycles on the dashboard", "pomodoro"),
    ("🔧 Settings", "snooze, notifications, sounds, 12/24h", "settings"),
    ("👋 Quit", "leave (alarms won't ring while away)", "quit"),
    ("◂  back to the prompt", "or just press Esc", "back"),
)

# examples shown under the banner: (what to type, what it does)
EXAMPLES = (
    ("wake me at 7:30", "set a morning alarm"),
    ("remind me in 20 minutes to stretch", "a quick reminder"),
    ("show my alarms", "what's coming up"),
    ("start the clock", "alarms ring on this screen"),
)

# slash-command palette: shown for "/", typos, and used for Tab completion
SLASH_PALETTE = (
    ("/add", "set an alarm at a time"),
    ("/remind", "quick reminder (also /in)"),
    ("/list", "show alarms with countdowns"),
    ("/next", "just the next alarm"),
    ("/edit", "change an alarm"),
    ("/remove", "delete an alarm"),
    ("/enable", "switch an alarm on"),
    ("/disable", "switch an alarm off"),
    ("/run", "start the clock — alarms ring here"),
    ("/timer", "countdown (e.g. /timer 10m)"),
    ("/stopwatch", "elapsed-time clock"),
    ("/sound", "preview a sound"),
    ("/every", "recurring reminder (/every 30m water)"),
    ("/skip", "skip an alarm's next ring"),
    ("/pause", "all alarms off (remembers which)"),
    ("/resume", "bring back what /pause turned off"),
    ("/pomodoro", "work/break cycles (25/5x4)"),
    ("/daemon", "background ringer: rings with no terminal open"),
    ("/snooze", "snooze whatever is ringing right now"),
    ("/dismiss", "dismiss whatever is ringing right now"),
    ("/settings", "snooze length, sounds, 12/24h"),
    ("/menu", "open the menu"),
    ("/help", "all the plain-English examples"),
    ("/quit", "leave the shell"),
)

# actions that "do something" — worth following with a fresh tip
_DOING = {
    "add", "in", "every", "edit", "remove", "enable", "disable",
    "skip", "pause", "resume", "timer", "settings",
}


def _print_palette() -> None:
    print(style("Commands", "bold") + style("  (Tab completes; plain English works too)", "dim"))
    width = max(len(cmd) for cmd, _ in SLASH_PALETTE) + 3
    for cmd, desc in SLASH_PALETTE:
        print("  " + style(cmd.ljust(width), "cyan") + style(desc, "dim"))


def _help_text() -> str:
    def cmd(text):
        return style(text, "cyan")

    def note(text):
        return style(text, "dim")

    sections = [
        (style("Alarms", "bold"), [
            (cmd("wake me at 7:30") + "   " + cmd("set an alarm for 10pm") + "   " + cmd("7:30"),
             note("asks a label and whether to repeat")),
            (cmd("alarm at 6:45am every weekday"), note("times are flexible: 7:30, 0730, 7pm, 12am")),
        ]),
        (style("Reminders", "bold"), [
            (cmd("remind me in 20 minutes to stretch"), note("one line, done")),
            (cmd("remind me tomorrow at 9am to submit the report"), ""),
            (cmd("remind me every 30 minutes to drink water"), note("recurring")),
            (cmd("remind me in 1h") + "   " + cmd("in 90s") + "   " + cmd("25m"),
             note("asks what it's for")),
        ]),
        (style("See & change", "bold"), [
            (cmd("show my alarms") + "   " + cmd("list") + "   " + cmd("next"), ""),
            (cmd("edit") + " / " + cmd("change my alarm"), note("pick one, change anything")),
            (cmd("remove") + " / " + cmd("delete") + "     " + cmd("enable") + " / " + cmd("disable"), ""),
            (cmd("skip"), note("skip an alarm's next ring, keep the schedule")),
            (cmd("pause") + " / " + cmd("resume"), note("everything off for a while, then back")),
        ]),
        (style("The clock", "bold") + "  " + style("— alarms only RING while this is open", "yellow"), [
            (cmd("start the clock") + " / " + cmd("run"),
             note("s snoozes · d dismisses · q quits")),
        ]),
        (style("Extras", "bold"), [
            (cmd("timer 10m") + "   " + cmd("pomodoro") + "   " + cmd("stopwatch"), ""),
            (cmd("sound") + "   " + cmd("settings"), ""),
        ]),
        (style("Leaving", "bold"), [
            (cmd("quit") + " / " + cmd("exit") + " / Ctrl-D", ""),
        ]),
    ]
    lines = [style("What you can say", "bold", "cyan"), ""]
    for title, rows in sections:
        lines.append(f" {title}")
        for left, right in rows:
            lines.append(f"   {left}" + (f"   {right}" if right else ""))
        lines.append("")
    lines.append(
        note("Shortcuts: Enter = menu · slash commands (/add, /list, ...) work too · Esc backs out")
    )
    return "\n".join(lines)


def _status_line(state, now) -> str:
    enabled = [a for a in state.alarms if a.enabled]
    status = f"{len(enabled)} alarm{'s' if len(enabled) != 1 else ''}"
    found = next_alarm(state.alarms, now)
    if found:
        alarm, ring = found
        status += f" · next: {alarm.label or alarm.id} in {timeparse.format_delta(ring - now)}"
    return status


def _tilde(path) -> str:
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def _coming_up(state, now, limit: int = 3) -> str | None:
    """'coming up: standup in 13h · tea in 24m' — the next few, soonest first."""
    upcoming = sorted(
        ((next_ring(a, now), a) for a in state.alarms if next_ring(a, now)),
        key=lambda pair: pair[0],
    )[:limit]
    if not upcoming:
        return None
    parts = [
        f"{alarm.label or alarm.id} in {timeparse.format_delta(ring - now)}"
        for ring, alarm in upcoming
    ]
    return "coming up: " + " · ".join(parts)


def _banner() -> None:
    state = Store().load()
    now = datetime.now()
    # (plain, styled) pairs: pad by the plain text so ANSI codes don't skew the box
    rows = [
        ("  ⏰ better-alarm", "  ⏰ " + style("better-alarm", "bold", "cyan")),
        ("     your terminal alarm clock", style("     your terminal alarm clock", "dim")),
        ("", ""),
        (f"  {_status_line(state, now)}", f"  {_status_line(state, now)}"),
        (f"  data: {_tilde(data_path())}", style(f"  data: {_tilde(data_path())}", "dim")),
    ]
    preview = _coming_up(state, now)
    if preview:
        rows.insert(4, (f"  {preview}", "  " + style(preview, "dim")))
    # the clock emoji renders two columns wide but counts as one character
    width = max(len(plain) + plain.count("⏰") for plain, _ in rows) + 3
    print(style("╭" + "─" * width + "╮", "cyan"))
    for plain, styled in rows:
        pad = " " * (width - len(plain) - plain.count("⏰") - 1)
        print(style("│", "cyan") + " " + styled + pad + style("│", "cyan"))
    print(style("╰" + "─" * width + "╯", "cyan"))

    print()
    print(" " + style("Try these — just type one:", "bold"))
    left_width = max(len(what) for what, _ in EXAMPLES) + 3
    for what, why in EXAMPLES:
        print("   " + style(what.ljust(left_width), "cyan") + style(why, "dim"))
    print()
    print(
        " "
        + style("Enter", "bold") + style(" → menu (↑/↓, Esc)  ·  ", "dim")
        + style("help", "bold") + style(" → all examples  ·  ", "dim")
        + style("quit", "bold") + style(" → leave", "dim")
    )
    if state.config.tips:
        print(" " + style("✦", "yellow") + style(f" tip: {tips.daily_tip(now.date())}", "dim"))
    print()


def _offer_clock(parser) -> None:
    """An alarm that can't ring is a broken promise — go straight to the clock."""
    from . import cli

    print(style("starting the clock so it can ring — press q to come back here", "dim"))
    cli.cmd_run(parser.parse_args(["run"]))
    print(style("clock stopped — you're back at the prompt", "dim"))


def _dispatch(intent: Intent, parser) -> bool:
    """Act on one intent. Returns True when the shell should exit."""
    from . import cli  # deferred: cli imports this module's caller

    action = intent.action
    if action == "back":
        return False
    if action == "quit":
        from . import daemon

        found = next_alarm(Store().load().alarms, datetime.now())
        if found and daemon.is_running():
            found = None  # the background ringer has it covered
        if found:
            alarm, ring = found
            print(
                " " + style("⚠", "yellow")
                + style(
                    f" '{alarm.label or alarm.id}' is due in "
                    f"{timeparse.format_delta(ring - datetime.now())} but will NOT ring unless "
                    "the clock is running — start it with `alarm run`",
                    "yellow",
                )
            )
        print(style("bye!", "dim"))
        return True
    if action == "help":
        print(_help_text())
    elif action == "commands":
        _print_palette()
    elif action == "add":
        args = parser.parse_args(["add"])
        args._in_shell = True
        args.time = intent.time
        if intent.label:
            args.label = intent.label
        interactive.add_prompts(args)
        cli.cmd_add(args)
        _offer_clock(parser)
    elif action == "in":
        args = parser.parse_args(["in"])
        args._in_shell = True
        args.duration = intent.duration
        if intent.label:
            args.label = intent.label
        interactive.in_prompts(args)
        cli.cmd_in(args)
        _offer_clock(parser)
    elif action == "every":
        args = parser.parse_args(["every"])
        args._in_shell = True
        args.duration = intent.duration
        if intent.label:
            args.label = intent.label
        cli.cmd_every(args)
        _offer_clock(parser)
    elif action == "skip":
        cli.cmd_skip(parser.parse_args(["skip"]))
    elif action == "pause":
        cli.cmd_pause(parser.parse_args(["pause"]))
    elif action == "resume":
        cli.cmd_resume(parser.parse_args(["resume"]))
    elif action == "pausetoggle":  # one menu item, does the right thing
        if Store().load().config.paused_ids:
            cli.cmd_resume(parser.parse_args(["resume"]))
        else:
            cli.cmd_pause(parser.parse_args(["pause"]))
    elif action == "pomodoro":
        cli.cmd_pomodoro(parser.parse_args(["pomodoro"]))
    elif action == "daemon":
        cli.cmd_daemon(parser.parse_args(["daemon"]))
    elif action == "dismiss":
        cli.cmd_dismiss(parser.parse_args(["dismiss"]))
    elif action == "snooze":
        cli.cmd_snooze(parser.parse_args(["snooze"]))
    elif action == "edit":
        cli.cmd_edit(parser.parse_args(["edit"]))
    elif action == "remove":
        cli.cmd_remove(parser.parse_args(["remove"]))
    elif action in ("enable", "disable"):
        cli.cmd_toggle(parser.parse_args([action]))
    elif action == "list":
        cli.cmd_list(parser.parse_args(["list"]))
    elif action == "next":
        cli.cmd_next(parser.parse_args(["next"]))
    elif action == "run":
        cli.cmd_run(parser.parse_args(["run"]))
        print(style("clock stopped — you're back at the prompt", "dim"))
    elif action == "timer":
        duration = intent.duration or interactive.ask(
            "How long? (e.g. 10m, 1h30m)", parse=lambda raw: (timeparse.parse_duration(raw), raw)[1]
        )
        cli.cmd_timer(parser.parse_args(["timer", duration]))
    elif action == "stopwatch":
        cli.cmd_stopwatch(parser.parse_args(["stopwatch"]))
    elif action == "sound":
        name = interactive.ask("Which sound? (bell, system:Glass, default)", default="default")
        cli.cmd_test_sound(parser.parse_args(["test-sound", name]))
    elif action == "settings":
        cli.cmd_config_show(None)
        if interactive.confirm("change a setting?"):
            cli.cmd_config_set(parser.parse_args(["config", "set"]))
    else:
        print(
            style("didn't catch that", "yellow")
            + style(' — try "remind me in 20 minutes", or press Enter for the menu', "dim")
        )
    return False


def _history_file():
    from .config import data_dir

    return data_dir() / "history"


def _load_history() -> None:
    if not interactive.HAS_READLINE:
        return
    import readline

    try:
        readline.read_history_file(_history_file())
    except OSError:
        pass


def _save_history() -> None:
    if not interactive.HAS_READLINE:
        return
    import readline

    try:
        _history_file().parent.mkdir(parents=True, exist_ok=True)
        readline.set_history_length(200)
        readline.write_history_file(_history_file())
    except OSError:
        pass


def _setup_completion() -> None:
    """Tab completes slash commands (and a few natural openers)."""
    if not interactive.HAS_READLINE:
        return
    import readline

    vocab = [cmd for cmd, _ in SLASH_PALETTE] + [
        "wake me at ", "remind me in ", "set an alarm for ", "show my alarms",
        "start the clock", "menu", "help", "quit",
    ]

    def complete(text: str, state: int):
        matches = [w for w in vocab if w.startswith(text)] if text else list(vocab)
        return matches[state] if state < len(matches) else None

    readline.set_completer(complete)
    readline.set_completer_delims("\n")  # complete the whole line, not the last word
    if "libedit" in (readline.__doc__ or ""):  # macOS ships libedit, not GNU readline
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def run_shell(parser) -> int:
    _banner()
    _load_history()  # ↑/↓ recall previous commands, across sessions
    _setup_completion()  # Tab completes /commands
    actions_done = 0
    try:
        while True:
            try:
                raw = interactive.input_line()
            except Cancelled:
                print()
                return 0
            except KeyboardInterrupt:
                print(style('\n(type "quit" or press Ctrl-D to leave)', "dim"))
                continue
            intent = parse_intent(raw) if raw else Intent("menu")
            if intent.action == "menu":
                try:
                    choice = interactive.pick(
                        "What do you want to do?",
                        [(label, desc) for label, desc, _ in MENU],
                    )
                except Cancelled:
                    continue
                intent = Intent(MENU[choice][2])
            try:
                if _dispatch(intent, parser):
                    return 0
            except Cancelled:
                print(style("cancelled.", "dim"))
                continue
            except UserError as exc:
                print(style(f"error: {exc}", "red"))
                continue
            if intent.action in _DOING and Store().load().config.tips:
                actions_done += 1
                print(
                    " " + style("✦", "yellow")
                    + style(f" tip: {tips.tip_at(datetime.now().date(), actions_done)}", "dim")
                )
    finally:
        _save_history()
