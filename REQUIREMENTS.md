# Requirements - better-alarm

> **Process note:** The brief was one line - *"Build an alarm clock as a Python CLI application. CLI only, no web UI, no React, no database."* - with instructions to use AI to refine requirements, design, and an implementation plan before coding. This document is the output of that refinement: an AI-assisted, question-driven pass that turned the one-liner into testable requirements, followed by an iterative feedback loop that reshaped the product after using it (section 5). [DESIGN.md](DESIGN.md) records the architecture decisions; [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) records the build order.

## 1. Interpreting the brief

Ambiguities in the brief, and how each was resolved:

| Question | Decision | Rationale |
|---|---|---|
| Does "no database" forbid persistence entirely? | **No - JSON file persistence.** | "No database" reads as "no DB server/ORM". An alarm clock that forgets alarms on exit is barely a product. A single JSON file keeps the spirit of the constraint. |
| Third-party packages allowed? | **Zero runtime dependencies** on macOS/Linux (Windows needs `tzdata` for timezone support only). Optional visual upgrade if `rich` happens to be installed; `pytest` for dev. | The reviewer should be able to `python -m betteralarm` with nothing but a Python >= 3.10 install. Building the UI from raw ANSI also demonstrates fundamentals. |
| What interaction model does a *CLI* alarm clock have? | **Three layers:** Unix-style subcommands for scripts, a conversational shell for humans, and a live full-screen `run` mode that actually rings. | Pure subcommands are hostile to non-experts; a pure interactive app is not scriptable. Each layer drives the same handlers. |
| Can a CLI ring when it isn't running? | **v1.0: no, and we said so.** `run` was the "clock is on" mode; missed alarms were detected and reported. **v1.1: yes** - an optional background daemon (launchd/systemd user unit) rings with no terminal open. | Honest scoping first, then closing the biggest product gap once the core was solid. |
| Who is the user? | **Both a terminal-fluent developer and a first-time user.** Every function must be reachable without reading documentation. | This drove the shell, the self-describing menu, prompts for missing arguments, and plain-language error messages. |

## 2. Functional requirements

### F1. Alarm management (subcommands)
- **F1.1** `alarm add TIME [LABEL]` creates an alarm. TIME accepts `7:30`, `07:30`, `0730`, `730`, `7`, `7am`, `7:30pm`, `6:03 pm` (spaces tolerated), `12am` (=00:00), `12pm` (=12:00). Invalid input produces a helpful error listing accepted formats, exit code 2.
- **F1.2** Repeat rules via `--repeat`: `once` (default), `daily`, `weekdays`, `weekends`, or custom day lists (`mon,wed,fri` - 3-letter prefixes, case-insensitive).
- **F1.3** `alarm in DURATION [LABEL]` sets a one-shot alarm relative to now (`25m`, `1h30m`, `90s`, bare integer = minutes). The countdown is anchored to the moment the duration is known: time spent typing a label must not delay the ring.
- **F1.4** Natural dates: `alarm add "tomorrow 9am"`, `"today 23:15"`, `"monday 7pm"` (next occurrence), `"aug 20 14:00"` (this year, else next). A date implies a one-shot; combining with `--repeat` is an error.
- **F1.5** Timezones: `--tz Region/City` interprets the given wall time in that zone and converts to local (stdlib `zoneinfo`). Unknown zones get an error with an example.
- **F1.6** Recurring intervals: `alarm every 30m water` rings every 30 minutes; dismissing re-anchors the next occurrence.
- **F1.7** `alarm list [--all] [--json]` shows a table: id, label, schedule, sound, and next ring, sorted soonest-first; countdowns within 10 minutes render red, within the hour yellow (TTY only). `--json` emits clean machine-readable output even while missed alarms are being swept.
- **F1.8** `alarm next [--json]` prints the single next alarm; exit code 1 if none.
- **F1.9** `alarm remove|rm`, `alarm edit`, `alarm enable|disable`, `alarm skip` (suppress only the next occurrence), `alarm pause`/`alarm resume` (switch everything off remembering which, then back). Alarms are addressable by id prefix **or** label; ambiguity is an error naming the candidates.
- **F1.10** Per-alarm options: `--sound`, `--snooze` minutes, `--open URL` (opened in the browser when the alarm fires).
- **F1.11** Any command invoked without its required arguments prompts for them interactively (TTY only); scripts get a usage error instead of a hang. After every guided action the equivalent one-liner is printed so the user learns the fast path.

### F2. The live clock (`alarm run`)
- **F2.1** Full-screen dashboard: large block-glyph clock (cyan on TTY), date, next-alarm countdown, compact alarm list, key hints.
- **F2.2** When an alarm becomes due, it **rings**: a steady highlighted banner (bold yellow, never strobing or reverse-video) shows the label, and the sound is struck continuously - short system sounds are re-triggered on a tight period so the ring never decays into occasional dings.
- **F2.3** While ringing: `s` snoozes (per-alarm or default duration), `1`-`9` snoozes exactly that many minutes, `d`/`Enter` dismisses. While idle: `q` quits. The hint line always shows the real configured values.
- **F2.4** Unattended ringing auto-snoozes after N minutes, up to a max count, then auto-dismisses (all configurable, and stated on the ring screen) - the alarm never rings forever.
- **F2.5** Snooze state persists across restarts. Dismissing a one-shot disables it; a repeat schedules its next occurrence; an interval re-anchors.
- **F2.6** `run` picks up changes made from another terminal within one tick, and merges its own saves so an external `alarm add` is never clobbered by a concurrent dismiss-save.
- **F2.7** Ctrl-C at any moment - including mid-ring - restores the terminal and kills the sound. Non-TTY or `--plain` degrades to line-per-event log output.
- **F2.8** Timers and pomodoro phases draw a progress bar under the clock.

### F3. Missed alarms
- **F3.1** A one-shot alarm whose time passed while nothing was running is reported as MISSED on the next `list`/`next`/`run`, then disabled.
- **F3.2** On startup, anything due within the last 5 minutes (grace window) rings immediately, unless that occurrence was skipped or already dismissed.

### F4. Sound and notifications
- **F4.1** Sound specs: `bell`, `system:NAME`, `file:/path`, `default`. Platform backends with graceful fallback (afplay, paplay/aplay/ffplay, winsound, terminal bell); a broken backend falls back to bell rather than going silent. `alarm test-sound` previews naturally; real rings use the insistent re-strike period.
- **F4.2** Sound stops immediately on dismiss/snooze/quit; no orphaned processes on any exit path.
- **F4.3** Every fire also raises a native desktop notification (osascript on macOS, notify-send on Linux) so a buried terminal still gets attention. Configurable via `notifications`; content is quoted so labels cannot inject script.

### F5. Configuration
- **F5.1** `alarm config show|get KEY|set KEY VALUE` with validation, also browsable interactively via `settings` in the shell.
- **F5.2** Keys: `snooze_minutes` (5), `time_format` (24|12), `sound_enabled` (true), `default_sound` (`system:Glass`), `auto_action` (snooze|dismiss), `auto_action_minutes` (5), `max_auto_snoozes` (3), `tips` (true), `notifications` (true), `paused_ids` (managed by pause/resume).

### F6. The conversational shell (bare `alarm`)
- **F6.1** Running `alarm` with no arguments on a TTY opens a shell: a welcome banner (status, "coming up" preview of the next three alarms, examples to try, a rotating tip), then a `❯` prompt between two full-width rules.
- **F6.2** Plain English works: "wake me at 7:30", "set an alarm for 10pm", "remind me in 20 minutes to stretch", "remind me tomorrow at 9am to submit the report", "remind me every 30 minutes to drink water", "show my alarms", "change my alarm", "delete", "skip", "pause", bare "25m" or "7:30". Extracted values (time, duration, label) are prefilled; anything missing is asked one question at a time. A wrong answer re-asks with examples; it never dumps the user back to the shell.
- **F6.3** Slash commands mirror every feature; typing `/` alone (or a typo like `/frobnicate`) shows the full palette with descriptions; Tab completes commands and common openers.
- **F6.4** Empty Enter opens an arrow-key menu where every item carries an icon and a plain-words description of what will happen; choosers show their own key hints; destructive lists end with an explicit cancel option; the menu has a "back to the prompt" entry.
- **F6.5** There is always a way out: Esc leaves any menu; typing `back` or `cancel` (or Ctrl-D) leaves any question.
- **F6.6** Up/Down at the prompt recall previous commands; history persists across sessions.
- **F6.7** After an alarm or reminder is set, the clock starts automatically so it can ring; quitting with a pending alarm warns loudly - unless the background daemon is running, in which case no warning is needed.
- **F6.8** Unknown input gets a gentle nudge; unknown subcommands on the CLI get "did you mean?".

### F7. Background daemon
- **F7.1** `alarm daemon install|uninstall|status|run`. Install registers a login-persistent service (launchd agent on macOS, systemd user unit on Linux; Windows reports unsupported) running the headless ring loop.
- **F7.2** The daemon fires sound, desktop notification, and `--open` URLs with no terminal open, follows the data file live, applies the same auto-snooze policy, and logs to the data directory.
- **F7.3** `alarm snooze [MIN]` and `alarm dismiss` control whatever is due right now from any terminal; the daemon (or the fullscreen clock) notices the change and ends the ring.
- **F7.4** The daemon and the fullscreen clock never double-ring: the clock maintains a heartbeat file while open, and the daemon stays silent while it is fresh.

### F8. Extras
- **F8.1** `alarm timer DURATION [LABEL]` - countdown on the dashboard with progress bar (ephemeral).
- **F8.2** `alarm stopwatch` - big elapsed clock with laps.
- **F8.3** `alarm pomodoro [W/BxR]` - work/break cycles (default 25/5x4) with a tomato round tracker; `n` skips a phase, `q` stops the whole session cleanly.
- **F8.4** `alarm import FILE.ics [--before MIN]` - future timed calendar events become alarms, optionally ringing early. Handles folded lines, escaped text, UTC/TZID/floating times; all-day events are skipped.

## 3. Non-functional requirements

- **N1.** Zero runtime dependencies on macOS/Linux; Python >= 3.10; CI runs the matrix ubuntu/macos/windows x 3.10/3.12.
- **N2.** Robust persistence: atomic writes; corrupted files quarantined with a warning, never a traceback; unknown JSON keys ignored; versioned schema with a migration hook.
- **N3.** Testability by construction: all timing logic is pure and takes `now` as a parameter; interactive flows take injectable input functions; the daemon loop takes injectable clock, sleep, notifier, and player. No sleeps or mocking libraries in the suite.
- **N4.** Terminal safety: alternate screen and cursor restore guaranteed; graceful behavior on tiny terminals and non-TTY output.
- **N5.** Color discipline: ANSI styling only on a real TTY; plain text in pipes and under `NO_COLOR`; `--json` output is never decorated.
- **N6.** Exit codes: 0 success, 1 "nothing found/ringing", 2 user error, 130 SIGINT.

## 4. Out of scope (deliberate)

- Background daemon on Windows (schtasks integration; documented as unsupported).
- Per-keystroke floating suggestion popups (would require replacing readline with a custom line editor, losing history/editing).
- Sound file bundling, theming, cloud sync, accounts, telemetry.

## 5. How v1.1 happened (the iteration)

v1.0 shipped the subcommand CLI and the fullscreen clock. Everything after came from using the product and feeding observations back through the same refine-design-test loop, one round at a time:

1. *"Not every user knows what to run"* led to prompts for missing arguments, then the conversational shell, the intent parser, the menu, and the slash palette.
2. *"My alarm didn't ring"* (the clock wasn't open) led to the auto-started clock, loud quit warnings, then desktop notifications, and finally the daemon - closing the gap for real.
3. *"Editing is confusing"* and transcripts of real sessions led to the save-as-you-go edit flow, the `6:03 pm` parser fix, and the ring-time countdown anchor.
4. *"The flashing is unpleasant"* and *"rely more on visuals"* led to the steady banner, the icon menu, progress bars, and urgency colors.
5. CI's first run on Windows and Python 3.10 caught three real portability bugs the development machine could not (f-string syntax, missing tz database, USERPROFILE), which is exactly why the matrix exists.

Every round was test-first: 472 tests at the end, sub-second, no sleeps.
