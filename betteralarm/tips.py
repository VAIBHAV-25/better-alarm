"""One-line tips, rotated deterministically by day (no randomness, no state)."""

from __future__ import annotations

from datetime import date

TIPS = (
    "`alarm in 25m tea` sets a quick one-shot reminder",
    "`alarm daemon install` makes alarms ring even with every terminal closed",
    "while something rings, press 1-9 to snooze exactly that many minutes",
    "natural dates work: try `wake me tomorrow at 9am` or `alarm add \"monday 7pm\"`",
    "`remind me every 30 minutes to drink water` sets a recurring reminder",
    "`alarm skip wake` skips just the next ring and keeps the schedule",
    "going away? `alarm pause` switches everything off; `alarm resume` brings it back",
    "`alarm add 7:30 wake --repeat weekdays` skips weekends",
    "just type `alarm edit` — it will ask you what to change",
    "type `/` alone to see every command; Tab completes them",
    "`alarm pomodoro` runs 25/5 work-break cycles with a progress bar",
    "an alarm can open your meeting link when it rings: add `--open https://...`",
    "walked away mid-ring? it auto-snoozes, then gives up — never rings forever",
    "a ring can be handled from any terminal: `alarm snooze` or `alarm dismiss`",
    "`alarm timer 10m pasta` runs a countdown without saving an alarm",
    "`alarm test-sound system:Glass` previews a sound before you commit",
    "times are flexible: 7:30, 0730, 7pm, 12am all work",
    "turn these tips off with `alarm config set tips false`",
)


def tip_at(day: date, offset: int) -> str:
    """The day picks a starting point; the offset walks tips within a session."""
    return TIPS[(day.toordinal() + offset) % len(TIPS)]


def daily_tip(day: date) -> str:
    return tip_at(day, 0)
