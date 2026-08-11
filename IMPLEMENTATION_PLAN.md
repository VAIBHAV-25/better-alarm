# Implementation Plan - better-alarm

Ordered, test-first build. Each step: write the tests, watch them fail, implement, go green. See [DESIGN.md](DESIGN.md) for the architecture these steps realize. The plan has two phases: the v1.0 core, then the v1.1 iteration driven by real use (REQUIREMENTS.md section 5).

## Module map

| Module | Responsibility | Test file |
|---|---|---|
| `timeparse.py` | parse times/days/durations/natural dates, format deltas & clocks | `test_timeparse.py` |
| `models.py` | `Alarm` dataclass (once/repeat/interval), (de)serialization | `test_models.py` |
| `config.py` | `Config` dataclass, data-dir resolution | `test_models.py` |
| `store.py` | atomic JSON persistence, quarantine, migrations | `test_store.py` |
| `scheduler.py` | `next_ring`, `next_alarm`, `missed`, skip/interval math (pure) | `test_scheduler.py` |
| `engine.py` | IDLE⇄RINGING state machine, events, target cache, digit snooze | `test_engine.py` |
| `bigfont.py` | 5-row block digit font | `test_bigfont.py` |
| `render.py` | pure `build_frame` (banner, progress bar); Plain/Rich/Log painters | `test_render.py` |
| `sound.py` | player backends, insistent re-strike period | `test_sound.py` |
| `keyboard.py` | single-key input (posix/windows/null), optional arrow decoding | `test_keyboard.py` |
| `notify.py` | desktop notifications (osascript/notify-send), safe quoting | `test_notify.py` |
| `colors.py` | ANSI styling that vanishes off-TTY and under NO_COLOR | `test_colors.py` |
| `interactive.py` | prompt toolkit: input_line/ask/pick/select/confirm, guided flows | `test_interactive.py`, `test_select.py`, `test_interactive_cli.py` |
| `intent.py` | free text → Intent (action + time/duration/label extraction) | `test_intent.py` |
| `shell.py` | the conversational REPL: banner, menu, palette, dispatch | `test_shell.py` |
| `tips.py` | rotating one-line tips (deterministic, user-language only) | `test_tips.py` |
| `ics.py` | minimal .ics parsing for calendar import | `test_ics.py` |
| `daemon.py` | headless ring loop, heartbeat, launchd/systemd service files | `test_daemon.py` |
| `cli.py` | argparse tree, thin handlers, json output, did-you-mean | `test_cli.py` |
| `run.py` | the live loop: render/keys/sound/notify wiring, timer, stopwatch | `test_run.py` |
| `render_rich.py` | optional prettier renderer when `rich` is installed | manual checklist |

## Phase 1 - the core (v1.0)

1. **Scaffold** - `pyproject.toml`, package skeleton, docs. Gate: `alarm --help` exits 0.
2. **timeparse** - parametrized accept/reject tables for times, days, durations.
3. **models + config** - roundtrip serialization, tolerant of unknown keys, schedule descriptions.
4. **store** - fresh load, roundtrip, corrupt-file quarantine, migration hook.
5. **scheduler** - once/repeat math, snooze precedence, day-boundary and strict-`>` edges.
6. **cli (management)** - add/in/list/next/remove/edit/enable/disable/config end-to-end; exit codes.
7. **bigfont, sound, render** - goldens; spec resolution with monkeypatched platform.
8. **engine** - fire/snooze/dismiss/auto-snooze exhaustion/missed sweep as event sequences.
9. **run.py** - wire everything; mtime live-reload; timer and stopwatch. Tested by a scripted keyboard that doubles as a fake clock.
10. **Polish** - RichRenderer, README, docs synced to code.

## Phase 2 - the iteration (v1.1)

Each round below came from using the product, was specified conversationally, and was built test-first. Order matters: every later round leans on the toolkit built in the earlier ones.

11. **Prompts for missing arguments** - `interactive.py` primitives with injectable input; every handler gains a fill-by-asking step; equivalent one-liners taught after each guided action.
12. **The shell** - `intent.py` (pure text → Intent), `shell.py` REPL, menu, slash palette, Tab completion, history; `tips.py`; `colors.py`; did-you-mean and friendly errors in `cli.py`.
13. **Ring UX** - steady banner replacing the flash; insistent sound period; digit snooze; countdown anchored at duration entry; auto-start the clock after setting; quit warnings.
14. **Visual pass** - icon menu with descriptions, progress bars, urgency colors in `list`, "coming up" banner preview, pomodoro round tracker.
15. **Scheduling depth** - natural dates (`parse_when`), `--tz`, `every` interval alarms, `skip`, `pause`/`resume`, `--open`, `--json`, `.ics` import, pomodoro with escape hatches (`q` stops all, `n` skips a phase).
16. **Notifications + daemon** - `notify.py`; `daemon.py` headless loop reusing the engine, remote `snooze`/`dismiss` through the data file, heartbeat coordination, launchd/systemd install/uninstall/status.
17. **CI + packaging** - GitHub Actions matrix (ubuntu/macos/windows x 3.10/3.12); metadata for distribution. The first matrix run caught three portability bugs; fixed same day.

## Verification checklist (manual, after all green)

1. `pip install -e ".[dev]" && pytest` - all 472 pass, no warnings.
2. `alarm` (bare) - banner with coming-up preview; "remind me in 20 minutes to stretch" works end to end; Enter opens the menu; Esc, `back`, and Ctrl-D all exit cleanly; ↑ recalls history; Tab completes `/ed` → `/edit`.
3. `alarm in 1m tea && alarm run` - clock ticks; at T: steady banner + continuous sound + desktop notification; `3` snoozes 3 minutes; re-ring; `d` dismisses; sound stops instantly.
4. Unattended ring → auto-snooze at 5 min; after 3 auto-snoozes → auto-dismiss. Ctrl-C mid-ring → shell restored, `pgrep afplay` empty.
5. Second terminal `alarm add 9:00 x` while `run` is live → appears within a second. `alarm snooze` / `alarm dismiss` from a second terminal end a ring.
6. `alarm daemon run` in a background process; alarm fires with no terminal UI (sound + notification); `alarm dismiss` stops it; heartbeat: while `alarm run` is open the daemon stays silent.
7. `alarm add "tomorrow 9am" gym`, `alarm add 2pm call --tz Asia/Kolkata`, `alarm every 45m water`, `alarm skip`, `alarm pause && alarm resume`, `alarm import cal.ics --before 10` - all behave as documented; `alarm list --json | python -m json.tool` parses.
8. `alarm pomodoro` - progress bar, tomato tracker; `n` skips a phase; `q` stops the whole session and returns to the prompt.
9. `echo garbage > ~/.better-alarm/alarms.json && alarm list` → warning + quarantine, no traceback. `alarm run --plain | cat` → log lines, no ANSI. Tiny terminal → small-clock fallback.
10. `NO_COLOR=1 alarm` → fully plain output; `pip install rich` upgrades `run`; uninstalling keeps plain working.
