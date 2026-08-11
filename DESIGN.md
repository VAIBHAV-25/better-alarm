# Design - better-alarm

Architecture and the reasoning behind it. Requirements live in [REQUIREMENTS.md](REQUIREMENTS.md); build order in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## 1. Shape of the system

```
                    ┌──────────────── pure logic (fully unit-tested) ────────────────┐
                    │                                                                │
 cli.py ─────────►  │  timeparse.py   scheduler.py   engine.py    render.build_frame │
 (argparse,         │  models.py      (next_ring)    (state       intent.py  tips.py │
  thin handlers)    │                                 machine)                       │
        ▲           └───────▲────────────────────▲───────────────────▲───────────────┘
        │                   │                    │                   │
 shell.py            store.py (JSON,      run.py (the live     daemon.py (headless
 (conversational      atomic, merge)       loop + heartbeat)    loop + heartbeat
  REPL, menu,               │                    │               check, service files)
  slash palette)     ~/.better-alarm/     keyboard.py  sound.py  notify.py  ics.py
        │              alarms.json        (termios/    (afplay/  (osascript/ (.ics
 interactive.py                            msvcrt,      insistent notify-     events)
 (ask/pick/select/                         arrows)      period)   send)
  confirm, colors.py)
```

The dividing line is **pure vs. I/O**. Everything that can be wrong in an interesting way - time parsing, next-occurrence math, the ringing state machine, intent extraction, frame layout - is a pure function of its inputs, with `now: datetime` always passed in explicitly. The I/O shells (terminal, keyboard, subprocess sound, notifications, file system, service managers) are thin, swappable, and mostly boring.

Three front ends drive the **same command handlers**: argparse subcommands (scripts), the conversational shell (humans), and the arrow-key menu (discovery). The shell parses free text into an `Intent`, prefills an argparse `Namespace`, and calls the ordinary handler - there is exactly one implementation of every operation.

## 2. Decisions and rationale

### D1. Single-threaded polling; no threads
The `run` loop blocks in `select()` on stdin with a timeout - **the timeout is the tick** (1.0 s idle, 0.25 s while ringing). Alarm resolution is one minute, so even a 1 s poll oversamples 60x. Rejected: a scheduler thread + UI thread; it buys nothing and costs locks, cross-thread terminal writes, and teardown edge cases.

### D2. Engine caches fire targets
`Engine.targets: {alarm_id: datetime}` holds each alarm's next occurrence, recomputed only on snooze/dismiss/edit/reload. The per-tick due check is `target <= now`. A fresh `next_ring` at the fire instant would already have moved past the occurrence (strict `>`); the cache pins it until handled, and the strict `>` guarantees a just-dismissed occurrence cannot reappear.

### D3. Three alarm types, naive local time
- `once` stores a concrete datetime `at`.
- `repeat` stores `time` (HH:MM) + `days` (ISO, 0=Mon); `next_ring` walks day offsets and returns the first match strictly after the floor.
- `interval` stores `interval_seconds`; the anchor is `last_dismissed or created_at`, so dismissing naturally re-anchors the cadence.

All stored datetimes are **naive local**. An alarm clock is wall-clock by nature: "07:30" must mean 07:30 on the wall after a DST shift. `--tz` converts a foreign wall time to local *at creation*; natural dates (`tomorrow 9am`, `monday 7pm`, `aug 20 14:00`) are resolved to concrete local datetimes by `parse_when(raw, now)`.

`skip_until` raises the search floor so `alarm skip` suppresses exactly one occurrence without touching the schedule.

### D4. Snooze is persisted state, not session state
`alarm.snooze_until` lives in the JSON and takes precedence in `next_ring`. Kill the program mid-snooze, restart, and the snooze still fires. Startup treats a snooze as the *effective* due time in both directions: lapsed within the 5-minute grace window rings immediately; lapsed beyond it is reported missed. Digit keys 1-9 while ringing snooze exactly that many minutes - snoozing is a one-keystroke negotiation, not a settings trip.

### D5. Sound loops without threads, insistently
`Player.tick()` - called every loop tick - respawns the play subprocess when it exits. Real rings additionally pass a **re-strike period** (0.9 s): a play is never allowed to run longer than that before being struck again, so a short system "ding" becomes a continuous ring instead of one lonely chime per second. Previews (`test-sound`) play naturally. `stop()` is called from event handling, a `finally`, and an `atexit` hook - no orphan `afplay` survives any exit path. A player that fails three times in a row falls back to the terminal bell rather than becoming a silent alarm.

### D6. Keyboard: cbreak, with optional arrow decoding
POSIX `tty.setcbreak` + `select` - single keypresses while Ctrl-C still delivers SIGINT. The dashboard drains escape sequences (a CSI tail split across SSH packets must never leak a fake `d` that dismisses a ring). The interactive selector opts into `arrows=True`, which decodes Up/Down and a lone Esc instead. Windows uses `msvcrt`; non-TTY gets a Null keyboard.

### D7. Rendering: pure frame, dumb painters, steady visuals
`build_frame(...) -> Frame` computes every string in the UI and is golden-tested. Painters just draw a `Frame`: PlainRenderer (raw ANSI, alternate screen, per-line clear-to-EOL repaints - no flicker), RichRenderer (only if `rich` is importable), LogRenderer (non-TTY / `--plain`). The ring banner is a steady bold-yellow box - an earlier full-screen inverse-video flash was removed after real use: strobing reads as glitchy, not urgent. The big clock paints cyan; timers carry a `progress` fraction rendered as a bar. Wide-emoji menu icons are chosen from one width class so columns stay aligned.

### D8. Crash-safe terminal and storage
Renderer and keyboard are context managers; the loop's `try/finally` stops sound and restores the screen. Every save is `mkstemp` → write → `fsync` → `os.replace` (atomic). Corrupt JSON is quarantined to `alarms.json.corrupt-<ts>` with a warning; the schema carries a version and a migration table; unparseable individual alarms are skipped, not fatal.

### D9. Store watching and merge-on-save
`run` reloads (when idle) if the file's mtime changes - `alarm add` from a second terminal appears within a tick. Before persisting its own changes, it re-reads a changed file and overlays per-alarm state on the disk version, so an external add can never be clobbered by a concurrent dismiss-save.

### D10. The shell: intent → prefill → the same handlers
`intent.parse_intent(text)` is a pure function from free text to `Intent(action, time, duration, label)`. It runs ordered keyword checks (quit/help/list/edit/...), then extraction: durations ("in 25 minutes" → `25m`), day+time phrases ("tomorrow at 9" → `tomorrow 9`), labels ("to drink water"). Wrong guesses are cheap by design: every extracted value is offered back through a prompt with the value as the default, so a misparse costs one keystroke, never a wrong alarm. Slash commands map through the same table; `/` alone and typos render the palette.

The prompt toolkit (`interactive.py`) has four primitives - `input_line` (one line between two full-width rules), `ask` (validate-and-retry), `pick`/`select` (numbered fallback / arrow-key pointer with descriptions), `confirm` - all taking injectable `input_fn`/`keys` so every flow is tested with scripted input. Esc, Ctrl-D, and the words `back`/`cancel` raise one `Cancelled` exception that unwinds any flow to the prompt. `readline` provides history (persisted to the data dir) and Tab completion; prompt color codes are wrapped in readline's zero-width markers so editing does not garble.

### D11. The daemon: the same engine, headless
`daemon_loop` is `run.py` minus keyboard and renderer: the identical `Engine` drives fire/auto-snooze/auto-dismiss, so ring semantics cannot diverge between foreground and background. Effects (notify, player, sleep, clock) are injected, making the loop testable to the second with a fake clock. Remote control needs no IPC: `alarm snooze`/`alarm dismiss` mutate the JSON file, and the daemon resolves an active ring against the fresh file (disabled, re-snoozed, or dismissed-at-or-after-target ⇒ end the session). Coordination with the fullscreen clock is a heartbeat file the clock touches every tick; while it is fresh the daemon goes silent. Service files are generated (launchd plist / systemd user unit) with output logged to the data directory.

### D12. Notifications are a bonus, never a crash
`notify()` shells out to osascript/notify-send when present and silently does nothing otherwise. Message strings are JSON-quoted before embedding in AppleScript so an alarm label cannot inject script.

### D13. Time is captured when it is known
`alarm in`/"remind me in 10 seconds" anchors the countdown at the moment the duration is entered, not when the label is finished - a slow typist must not push the ring later. The same principle shows up in the engine (targets pinned at fire time) and the daemon (external dismiss compared against the session's target).

## 3. Ringing state machine

```
             target <= now                        s / 1-9 / auto-snooze (< max)
   IDLE ────────────────────────► RINGING ───────────────────────────► IDLE
    ▲                                │        snooze_until = now + d       │
    │   d / Enter / auto-dismiss /   │                     snooze elapses  │
    └── external dismiss (file) ─────┘                  (RINGING again) ◄──┘
      once → enabled=False (spent)
      repeat → next occurrence        interval → re-anchor on dismissal
```

`Engine.tick(now)` and `Engine.handle_key(key, now)` return **events** (`Fired`, `Snoozed`, `Dismissed`, `Missed`, `Dirty`); the shells map events to side effects (sound, notification, URL open, saving). `Engine.abort_ring(now)` ends a session that was resolved elsewhere (another terminal, or the clock taking over from the daemon).

## 4. Data schema (v1)

```json
{
  "version": 1,
  "config": { "snooze_minutes": 5, "time_format": "24", "sound_enabled": true,
              "default_sound": "system:Glass", "auto_action": "snooze",
              "auto_action_minutes": 5, "max_auto_snoozes": 3,
              "tips": true, "notifications": true, "paused_ids": [] },
  "alarms": [
    { "id": "e5f6a7b8", "label": "standup", "type": "repeat",
      "at": null, "time": "09:25", "days": [0,1,2,3,4], "enabled": true,
      "sound": "bell", "snooze_minutes": null, "snooze_until": null,
      "created_at": "2026-08-01T10:00:00", "last_dismissed": null,
      "open_url": null, "skip_until": null, "interval_seconds": null }
  ]
}
```

Location: `~/.better-alarm/alarms.json`, overridable with `BETTER_ALARM_HOME` (also how tests isolate state). The same directory holds the shell history, the clock heartbeat, and the daemon log.

## 5. Testing strategy

- **No mocking libraries, no sleeps.** Pure functions take literal datetimes; 472 tests run in about a second.
- Interactive flows are driven by scripted `input_fn`s; the arrow selector by injected key streams; the run loop by a fake keyboard that doubles as a fake clock; the daemon loop by injected clock/sleep/notifier/player.
- CLI tests call `cli.main([...])` in-process against a tmp store and assert stdout plus resulting JSON.
- CI runs ubuntu/macos/windows x Python 3.10/3.12 - its first run caught three portability bugs (pre-3.12 f-string rules, Windows' missing tz database, `USERPROFILE` vs `HOME`), which is the point of the matrix.
- Deliberately not unit-tested: termios/msvcrt paths, real subprocess audio, launchctl/systemctl calls (thin shims over tested logic; covered by the manual checklist in IMPLEMENTATION_PLAN.md).

## 6. Future work (out of scope, acknowledged)

Windows daemon support; per-keystroke suggestion popups (needs a custom line editor); package distribution (PyPI/Homebrew); sound bundling; theming.
