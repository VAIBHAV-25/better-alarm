"""Atomic JSON persistence with corruption quarantine and schema migrations."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config, data_path
from .errors import UserError
from .models import Alarm

SCHEMA_VERSION = 1

# version -> migration taking a doc at that version to version+1
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


@dataclass
class AppState:
    config: Config
    alarms: list[Alarm] = field(default_factory=list)
    version: int = SCHEMA_VERSION


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or data_path()

    def load(self) -> AppState:
        try:
            doc = json.loads(self.path.read_text())
            if not isinstance(doc, dict):
                raise ValueError("root is not an object")
        except FileNotFoundError:
            return AppState(config=Config())
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            self._quarantine(exc)
            return AppState(config=Config())

        version = doc.get("version", 0)
        while version < SCHEMA_VERSION and version in MIGRATIONS:
            doc = MIGRATIONS[version](doc)
            version = doc.get("version", version + 1)

        alarms = []
        for raw in doc.get("alarms", []):
            try:
                alarms.append(Alarm.from_dict(raw))
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                print(
                    f"warning: skipping unreadable alarm {raw.get('id', '?') if isinstance(raw, dict) else '?'}: {exc}",
                    file=sys.stderr,
                )
        return AppState(
            config=Config.from_dict(doc.get("config", {})),
            alarms=alarms,
            version=SCHEMA_VERSION,
        )

    def save(self, state: AppState) -> None:
        doc = {
            "version": state.version,
            "config": state.config.to_dict(),
            "alarms": [a.to_dict() for a in state.alarms],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".alarms-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(doc, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def _quarantine(self, exc: Exception) -> None:
        target = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
        os.replace(self.path, target)
        print(
            f"warning: {self.path} was corrupt ({exc}); moved it to {target.name} and starting fresh",
            file=sys.stderr,
        )


def find_alarm(state: AppState, ident: str) -> Alarm:
    """Resolve an alarm by exact label first, then unique id prefix."""
    ident = ident.strip()
    by_label = [a for a in state.alarms if a.label == ident]
    if len(by_label) == 1:
        return by_label[0]
    by_prefix = [a for a in state.alarms if a.id.startswith(ident)]
    candidates = by_label or by_prefix
    if not candidates:
        raise UserError(f"no alarm matches {ident!r} (see `alarm list --all`)")
    if len(candidates) > 1:
        names = ", ".join(f"{a.id} ({a.label or 'no label'})" for a in candidates)
        raise UserError(f"{ident!r} matches multiple alarms: {names}")
    return candidates[0]
