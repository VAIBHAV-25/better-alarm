# better-alarm ⏰

A terminal alarm clock you talk to in plain English, with a live fullscreen
dashboard. Pure Python, **zero dependencies** - nothing to install beyond
Python ≥ 3.10.

```
────────────────────────────────────────────────────────
 ❯ remind me in 25 minutes to stir the soup
────────────────────────────────────────────────────────
✔ alarm 85adb65f 'stir the soup' - Aug 11 18:06 (rings in 25m)
※ next time, one line does this:  alarm in 25m 'stir the soup'
starting the clock so it can ring - press q to come back here

              ╭─────────────────────────────────╮
              │  ♪  RINGING - stir the soup  ♪  │
              ╰─────────────────────────────────╯

  █████ █████    █████ █████    █████ █████
  █   █    █         █ █        █   █ █   █
  █   █    █     █████ █████    █   █ █████
  █   █    █     █         █    █   █     █
  █████    █     █████ █████    █████ █████

                  Tue Aug 11, 2026
           unattended → auto-snooze in 5m
     [s] snooze 5 min   ·   [d/enter] dismiss
```

## Quickstart

Detailed step-by-step instructions live in [RUNNING.md](RUNNING.md).

```bash
# run straight from the repo (no install)
python -m betteralarm add 7:30 wake --repeat weekdays
python -m betteralarm run

# or install the `alarm` command
pip install -e .
alarm add 7:30 wake --repeat weekdays
alarm run
```

`alarm run` is the "clock is on" mode - alarms ring while it's on screen: a
steady highlighted banner appears and the sound is struck continuously
(never one lonely ding) until you act, `s` snoozes, `d` dismisses, `q` quits.

**Want alarms with no terminal open at all?** Install the background ringer:

```bash
alarm daemon install     # launchd (macOS) / systemd user unit (Linux)
```

From then on alarms fire anywhere - sound plus a desktop notification -
and you control a ring from any terminal with `alarm snooze` / `alarm
dismiss`. The daemon automatically goes quiet whenever the fullscreen
clock is open (nothing ever rings twice), applies your auto-snooze policy
so an unattended ring still never lasts forever, and logs to
`~/.better-alarm/daemon.log`. `alarm daemon status` / `uninstall` manage it.

Without the daemon, setting an alarm in the shell drops you straight into
the clock, quitting with a pending alarm warns you loudly, and anything
missed while nothing was running is reported (and marked) on your next
`list`/`next`/`run`.

## The interactive shell

New here? Just run `alarm` with no arguments. It opens a conversational
shell: a welcome banner with examples, then a `❯` prompt between two rules
that takes plain English:

```
────────────────────────────────────────────────────────
 ❯ wake me at 7:30
────────────────────────────────────────────────────────
Label?
────────────────────────────────────────────────────────
 ❯ gym
────────────────────────────────────────────────────────
✔ alarm 113fd999 'gym' - weekdays 07:30 (rings in 13h 48m)
```

- **Say it your way** - `wake me at 7:30`, `set an alarm for 10pm`,
  `remind me in 20 minutes to stretch`, `show my alarms`, `delete`,
  `change my alarm`, bare `25m` or `7:30`, or slash commands - type `/` alone to see them all, Tab completes them, and `/menu`, `/edit`, `/list` jump straight to the thing.
  Whatever the sentence doesn't say, a follow-up question asks.
- **A menu that explains itself** - press Enter on an empty line and every
  item has an icon and a plain-words description (`⏰ Set an alarm - wake up
  at a time`, `🔔 Start the clock - THE screen where alarms ring`). Choosers
  show `↑/↓ move · Enter select · Esc cancel` with a `❯` pointer, destructive
  lists end with `✕ cancel - keep everything`, and the menu itself has
  `◂ back to the prompt`.
- **A way out, always** - Esc leaves any menu; typing `back` or `cancel`
  (or Ctrl-D) leaves any question; ↑/↓ at the prompt recall previous
  commands, persisted across sessions.
- **Editing is conversational** - `edit` picks the alarm, asks what to
  change, confirms each change instantly (`✔ time → 8:15`), and plain Enter
  saves.
- **It teaches you** - every guided action prints its one-line equivalent
  (`※ next time: alarm edit gym --time 8:15`), rotating tips appear as you
  work (`alarm config set tips false` to silence), and typos get
  "did you mean?".

## Commands

Flags always work - for scripts, cron, and once you know them. Any command
missing its arguments (`alarm edit`, `alarm add`, ...) prompts for them
instead of erroring.

```bash
alarm add 7:30 wake --repeat weekdays     # daily | weekdays | weekends | mon,wed,fri | once
alarm add "tomorrow 9am" gym              # natural dates: today | tomorrow | monday | aug 20
alarm add 2pm call --tz Asia/Kolkata      # interpret the time in another timezone
alarm add 9:55 standup --open https://…   # opens the URL when it rings
alarm add 10pm winddown --sound bell --snooze 5
alarm in 25m tea                          # one-shot, relative ("1h30m", "90s", bare = minutes)
alarm every 30m water                     # recurring interval reminder
alarm list [--all] [--json]               # table (or JSON for scripts)
alarm next [--json]                       # the single next alarm (exit 1 if none)
alarm edit wake --time 8:00 --label sleep-in
alarm skip wake                           # skip the next ring, keep the schedule
alarm pause && alarm resume               # vacation mode: everything off, then back
alarm disable wake && alarm enable wake   # address by label or id prefix
alarm remove wake
alarm run [--plain]                       # the live clock (--plain: log lines, script-friendly)
alarm timer 10m pasta                     # countdown timer on the same dashboard (not saved)
alarm pomodoro [25/5x4]                   # work/break cycles on the dashboard
alarm stopwatch                           # big elapsed clock, [l] laps
alarm import calendar.ics --before 10     # calendar events become alarms, 10 min early
alarm test-sound system:Glass             # preview: bell | system:NAME | file:/path.wav
alarm config show                         # snooze, notifications, 12/24h, auto-snooze, ...
alarm config set snooze_minutes 5
```

Times parse flexibly: `7:30`, `07:30`, `0730`, `730`, `7`, `7am`, `7:30pm`, `12am`. An unattended ring auto-snoozes after 5 minutes (3×, then auto-dismisses) - configurable, so an alarm never rings forever.

## Nice touches

- **Desktop notifications** - a ring also raises a native notification (macOS/Linux), so you see it even when the terminal is buried. `alarm config set notifications false` to opt out.
- **Snooze your way** - `s` snoozes the configured length; `1`-`9` snoozes exactly that many minutes.
- **Snooze survives restarts** - it's persisted state, not session state.
- **Live reload** - `alarm add` from a second terminal shows up on a running dashboard within a second.
- **Crash-safe** - atomic writes; a corrupted data file is quarantined (never a traceback, never silent data loss); Ctrl-C mid-ring restores your terminal and kills the sound.
- **Degrades gracefully** - tiny terminal → small clock; non-TTY → line-per-event log; missing sound backend → terminal bell.
- **Optional eye candy** - `pip install rich` and `alarm run` upgrades itself; uninstall and it still works.
- **Colors that know their place** - cyan prompts, yellow warnings, dim hints on a TTY; plain text in pipes and under `NO_COLOR`.
- **A slow label can't delay the ring** - `remind me in 10 seconds` counts from the moment you said it, not from when you finish typing the label.
- Data is one human-editable JSON file at `~/.better-alarm/alarms.json` (`BETTER_ALARM_HOME` overrides).

## Development

```bash
pip install -e ".[dev]"
pytest          # 471 tests, no sleeps, no mocking libraries
```

All timing logic is pure - `next_ring(alarm, now)`, `Engine.tick(now)` - with `now` injected, so the whole scheduler and ringing state machine are tested with literal datetimes. Platform-specific terminal/sound shims are thin and covered by the manual checklist in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## The thinking (per the brief)

The task asked for AI-assisted refinement of requirements, design, and plan *before coding* - those artifacts ship in this repo:

1. **[REQUIREMENTS.md](REQUIREMENTS.md)** - how a one-line brief became testable requirements, including the interpretation calls (what "no database" means, how a CLI can "ring", missed-alarm semantics).
2. **[DESIGN.md](DESIGN.md)** - the architecture and each decision's rationale: single-threaded polling over threads, target caching in the engine, pure-core/IO-shell split, crash-safe storage.
3. **[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** - the ordered TDD build (tests were written first for every module) and the final manual verification checklist.
