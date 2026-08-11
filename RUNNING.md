# Running better-alarm

A step-by-step guide from a fresh terminal to a ringing alarm. Nothing here
needs anything beyond Python ≥ 3.10 - the app has zero dependencies.

## 1. Prerequisites

- Python 3.10 or newer (`python3 --version`)
- A terminal (macOS Terminal, iTerm2, or any Linux terminal)

Check you're in the project directory:

```bash
cd ~/Desktop/better-alarm
```

## 2. Choose how to invoke it

### Option A - run straight from the repo (no install)

If the repo already has a `.venv` (this one does):

```bash
.venv/bin/python -m betteralarm --help
```

Or with your system Python - the app has no dependencies, so this just works:

```bash
python3 -m betteralarm --help
```

### Option B - install the `alarm` command

```bash
python3 -m venv .venv                 # skip if .venv already exists
.venv/bin/pip install -e .
export PATH="$PWD/.venv/bin:$PATH"    # for this terminal session
alarm --help
```

Everything below uses `alarm`. If you chose Option A, substitute
`.venv/bin/python -m betteralarm` (or `python3 -m betteralarm`) wherever you
see `alarm`.

## 3. Set your first alarm

**Don't know the commands? You don't need them.** Just type `alarm` - it
opens a friendly conversational shell: a welcome banner with examples to
try, then a `❯` prompt between two full-width rules that takes plain
English:

```
────────────────────────────────────────────────────────
 ❯ remind me in 20 minutes to stretch
────────────────────────────────────────────────────────
✔ alarm a32d4a09 'stretch' - Aug 11 18:32 (rings in 20m)
※ next time, one line does this:  alarm in 20m stretch
starting the clock so it can ring - press q to come back here
```

Things to know, all discoverable inside the shell itself:

- Say what you want: `wake me at 7:30`, `set an alarm for 10pm`,
  `show my alarms`, `change my alarm`, `delete`, bare `25m` or `7:30`,
  or slash commands - type `/` alone for the full palette, Tab completes them, and `/menu`, `/edit`, `/list` jump straight there. Missing details are asked one question
  at a time - a wrong answer re-asks with examples, it never dumps you
  back to the shell.
- Press Enter on an empty line for the menu - every item has an icon and a
  plain-words description of what it does (`⏰ Set an alarm - wake up at a
  time`, `🔔 Start the clock - THE screen where alarms ring`). Choosers are
  arrow-key lists (`↑/↓ move · Enter select · Esc cancel`) with a `❯`
  pointer, the remove list ends with `✕ cancel - keep everything`, and the
  menu's last entry is `◂ back to the prompt`.
- You can always back out: Esc leaves any menu, typing `back` or `cancel`
  (or Ctrl-D) leaves any question.
- ↑/↓ at the prompt step through your previous commands - history is kept
  across sessions (in `~/.better-alarm/history`).
- After an alarm or reminder is set, the clock starts automatically so it
  can actually ring - press `q` to come back to the prompt. Quitting while
  an alarm is pending warns you it won't ring without the clock.
- Type `help` for the full cheatsheet, `quit` (or Ctrl-D) to leave.

The same friendliness works per command: `alarm add`, `alarm in`,
`alarm edit`, `alarm remove` with no arguments all prompt for what's
missing, and after each guided action they print the one-line equivalent
so you learn the fast path.

Or the direct way - a one-shot alarm relative to now:

```bash
alarm in 2m coffee
# ✔ alarm 3f9a12bc 'coffee' - Aug 11 17:20 (rings in 2m)
```

`2m` accepts other forms: `90s`, `1h30m`, or a bare number meaning minutes.
The label (`coffee`) is anything you like - you'll use it to refer to the
alarm later.

Or an alarm at a clock time, optionally repeating:

```bash
alarm add 7:30 wake --repeat weekdays   # daily | weekdays | weekends | mon,wed,fri | once
alarm add "tomorrow 9am" gym            # natural dates: today, tomorrow, monday, aug 20 ...
alarm add 2pm call --tz Asia/Kolkata    # a time in another timezone
alarm add 9:55 standup --open https://meet.example/x   # opens the link when it rings
alarm add 10pm winddown --sound bell --snooze 5
alarm every 30m water                   # recurring interval reminder
```

In the shell, the same things in plain English: `remind me tomorrow at 9am
to submit the report`, `remind me every 30 minutes to drink water`.

Times parse flexibly: `7:30`, `07:30`, `0730`, `730`, `7`, `7am`, `7:30pm`,
`12am`, plus natural dates like `tomorrow 9am` and `aug 20 14:00`. Times use
your machine's local clock unless you pass `--tz Region/City`.

Sanity-check what's scheduled:

```bash
alarm list      # table of alarms with next-ring countdowns
alarm next      # the single next alarm (exit code 1 if none)
```

## 4a. The set-and-forget way: the background ringer

```bash
alarm daemon install    # once; macOS (launchd) or Linux (systemd user unit)
```

Alarms now fire with **no terminal open**: the sound plays and a desktop
notification appears. While one is ringing, from any terminal:

```bash
alarm snooze        # or `alarm snooze 3` for exactly 3 minutes
alarm dismiss
```

The daemon defers to the fullscreen clock whenever it's open (nothing rings
twice), honors your auto-snooze policy (an unattended ring still gives up
eventually), and logs to `~/.better-alarm/daemon.log`. Check or remove it:

```bash
alarm daemon status
alarm daemon uninstall
```

## 4b. Start the clock - the fullscreen way

```bash
alarm run
```

Your terminal becomes a fullscreen dashboard: a big block-digit clock, the
date, the next alarm, and a table of everything scheduled, all updating live.

**Leave this running.** Alarms only ring while this screen is up - a CLI
can't ring when nothing is running. If an alarm's time passes while the
clock is off, it's reported (and marked missed) on your next
`list` / `next` / `run`.

Tip: keep `alarm run` in one terminal and manage alarms from a second one -
`alarm add` / `remove` / `edit` changes show up on the dashboard within a
second.

## 5. When it rings

A steady highlighted banner appears above the big clock (no strobing), and
the sound is struck continuously - short system sounds are re-triggered
back-to-back, never one lonely ding - until you act:

```
        ╭───────────────────────────╮
        │  ♪  RINGING - coffee  ♪   │
        ╰───────────────────────────╯
              <big block clock>
         unattended → auto-snooze in 5m
   [s] snooze 5 min   ·   [d/enter] dismiss
```

A native desktop notification fires at the same time (macOS/Linux), so a
buried terminal still gets your attention - `alarm config set notifications
false` to opt out. If the alarm has `--open`, its URL opens in your browser.

| Key | Action |
|-----|--------|
| `d` or Enter | dismiss |
| `s` | snooze (default 5 minutes - the hint shows the real value) |
| `1`-`9` | snooze exactly that many minutes |
| `q` | quit the dashboard (anytime) |

- Snooze is persisted - quit and restart, the snooze is still pending.
- Walk away and it auto-snoozes after 5 minutes, gives up after 3 rounds
  (the ring screen tells you this). An alarm never rings forever. Both are
  configurable (see below).
- Ctrl-C mid-ring is safe: terminal restored, sound killed, no traceback.

## 6. Managing alarms

The no-arguments way (in the shell or directly): `alarm edit` picks the
alarm with an arrow-key list, asks what to change with the current values
shown, confirms each change on the spot, and plain Enter saves:

```
What do you want to change?
   ↑/↓ move · Enter select · Esc cancel
 ❯ time    (09:25)
   label   (standup)
   repeat  (weekdays)
   sound   (default)
   snooze  (default min)
New time (e.g. 7:30, 7pm)
────────────────────────────────────────────────────────
 ❯ 8:15
────────────────────────────────────────────────────────
  ✔ time → 8:15
change anything else on 'standup'? [y/N]
────────────────────────────────────────────────────────
 ❯ 
────────────────────────────────────────────────────────
✔ alarm 7196618f 'standup' - weekdays 08:15 (rings in 13h 55m)
```

`alarm remove` works the same way, with an explicit `✕ cancel` option and a
y/N confirmation before anything is deleted.

The one-line way, once you know it:

```bash
alarm list --all                          # include disabled/fired alarms
alarm list --json                         # machine-readable (tmux, scripts, Raycast)
alarm edit wake --time 8:00 --label sleep-in
alarm skip wake                           # skip the next ring, keep the schedule
alarm pause && alarm resume               # vacation mode: all off, then back
alarm disable wake && alarm enable wake   # address by label or id prefix
alarm remove wake                         # (alias: rm)
```

## 7. Extras on the same dashboard

```bash
alarm timer 10m pasta        # countdown timer (not saved as an alarm)
alarm pomodoro               # 25/5 x4 work/break cycles (or e.g. `alarm pomodoro 50/10x2`)
alarm stopwatch              # big elapsed clock, [l] records laps
alarm import calendar.ics --before 10   # calendar events become alarms, 10 min early
alarm test-sound bell        # preview: bell | system:NAME | file:/path.wav
alarm test-sound system:Glass
```

## 8. Configuration

```bash
alarm config show
alarm config set snooze_minutes 5
```

Settings include snooze length, 12/24-hour display, the auto-snooze policy,
and `tips` (set to `false` to hide the rotating ✦ tips). In the shell, type
`settings` to browse and change them interactively.

## 9. Where your data lives

One human-editable JSON file: `~/.better-alarm/alarms.json`.

Set `BETTER_ALARM_HOME` to relocate it - handy for trying things without
touching your real alarms:

```bash
BETTER_ALARM_HOME=/tmp/alarm-sandbox alarm in 10s demo
BETTER_ALARM_HOME=/tmp/alarm-sandbox alarm run
```

Writes are atomic, and a corrupted file is quarantined rather than crashing
or silently losing data.

## 10. Quick end-to-end test (~15 seconds)

```bash
export BETTER_ALARM_HOME=/tmp/alarm-sandbox   # sandbox, real alarms untouched
alarm in 10s demo
alarm run          # watch it ring, press d to dismiss, q to quit
unset BETTER_ALARM_HOME
```

## Troubleshooting

- **`alarm: command not found`** - you're in Option A: use
  `.venv/bin/python -m betteralarm ...`, or do the Option B install.
- **No sound** - try `alarm test-sound bell`. With no sound backend
  available it falls back to the terminal bell; check your terminal allows
  the audible bell.
- **Nothing rang** - was `alarm run` on screen at ring time? It has to be.
  Check `alarm list --all` for a missed marker.
- **Tiny or garbled display** - the dashboard degrades to a small clock in
  tiny terminals and to line-per-event logs when not a TTY; `alarm run
  --plain` forces the log style (script-friendly).
- **Prettier dashboard** - optional: `pip install rich` and `alarm run`
  upgrades itself; uninstall and it still works.
- **Unwanted colors** - set the `NO_COLOR` environment variable; all
  styling degrades to plain text (it already does in pipes and scripts).

## Running the test suite

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest       # 471 tests, sub-second, no real sleeps
```
