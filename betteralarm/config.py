"""App configuration and data-file location."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    snooze_minutes: int = 5
    time_format: str = "24"  # "24" | "12"
    sound_enabled: bool = True
    default_sound: str = "system:Glass"
    auto_action: str = "snooze"  # "snooze" | "dismiss" when a ring goes unattended
    auto_action_minutes: int = 5
    max_auto_snoozes: int = 3
    tips: bool = True  # show rotating one-line tips in friendly contexts
    notifications: bool = True  # desktop notification when an alarm fires
    paused_ids: list = field(default_factory=list)  # alarms `alarm pause` switched off

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        config = cls(**{k: v for k, v in d.items() if k in known})
        # normalize hand-edited enums instead of silently misbehaving
        if config.time_format not in ("12", "24"):
            config.time_format = "24"
        config.auto_action = str(config.auto_action).lower()
        if config.auto_action not in ("snooze", "dismiss"):
            config.auto_action = "snooze"
        return config


def data_dir() -> Path:
    override = os.environ.get("BETTER_ALARM_HOME")
    return Path(override) if override else Path.home() / ".better-alarm"


def data_path() -> Path:
    return data_dir() / "alarms.json"
