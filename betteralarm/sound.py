"""Alarm sounds: platform backends with graceful fallback, no threads.

A ringing sound "loops" by having the run loop call Player.tick() every quarter
second; tick respawns the play subprocess when the previous run finished.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import Config

# Searched in order for `system:NAME` specs (NAME.aiff / NAME.wav / NAME.oga).
_SYSTEM_SOUND_DIRS = [
    "/System/Library/Sounds",                      # macOS
    "/usr/share/sounds/freedesktop/stereo",        # Linux (freedesktop theme)
    "/usr/share/sounds",                           # Linux misc
    "C:\\Windows\\Media",                          # Windows
]
_SOUND_EXTENSIONS = (".aiff", ".wav", ".oga", ".ogg", ".mp3")


def resolve_sound_path(spec: str, cfg: Config) -> str | None:
    """Turn a sound spec into a playable file path; None means the terminal bell."""
    if spec == "default":
        spec = cfg.default_sound
        if spec == "default":  # guard against a self-referencing config
            return None
    if spec == "bell":
        return None
    if spec.startswith("file:"):
        path = spec[len("file:"):]
        if Path(path).is_file():
            return path
        print(f"warning: sound file {path} not found; falling back to bell", file=sys.stderr)
        return None
    if spec.startswith("system:"):
        name = spec[len("system:"):]
        for directory in _SYSTEM_SOUND_DIRS:
            base = Path(directory)
            for ext in _SOUND_EXTENSIONS:
                candidate = base / f"{name}{ext}"
                if candidate.is_file():
                    return str(candidate)
        print(f"warning: system sound {name!r} not found; falling back to bell", file=sys.stderr)
        return None
    print(f"warning: unknown sound spec {spec!r}; falling back to bell", file=sys.stderr)
    return None


class SubprocessPlayer:
    """Plays a file via an external command (afplay/paplay/aplay/ffplay).

    With a `period`, a play is never allowed to run longer than that before
    being struck again — short system "dings" become a continuous, insistent
    ring instead of one ding per natural sound length.
    """

    _MAX_FAILURES = 3

    def __init__(self, cmd: list[str], period: float | None = None):
        self.cmd = cmd
        self.period = period
        self.proc: subprocess.Popen | None = None
        self._stopped = False
        self._failures = 0
        self._started_at = 0.0
        self._fallback: BellPlayer | None = None
        atexit.register(self.stop)

    def start(self) -> None:
        self._stopped = False
        self._started_at = time.monotonic()
        self.proc = subprocess.Popen(
            self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def tick(self) -> None:
        if self._stopped:
            return
        if self._fallback is not None:
            self._fallback.tick()
            return
        if self.proc is None:
            return
        code = self.proc.poll()
        if code is None:
            if self.period is not None and time.monotonic() - self._started_at >= self.period:
                self.proc.terminate()  # cap the play; strike again now
                self.start()
            return  # still playing
        if code != 0:
            # player is broken (audio daemon down, bad file): don't spawn-loop
            # 4x/second with a silent alarm — ring the bell instead
            self._failures += 1
            if self._failures >= self._MAX_FAILURES:
                print(
                    f"warning: {self.cmd[0]} keeps failing; ringing terminal bell instead",
                    file=sys.stderr,
                )
                self._fallback = BellPlayer()
                self._fallback.start()
                return
        else:
            self._failures = 0
        self.start()  # finished → loop

    def stop(self) -> None:
        self._stopped = True
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=1)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None


class WinsoundPlayer:
    """Windows native looping playback."""

    def __init__(self, path: str):
        self.path = path

    def start(self) -> None:
        import winsound

        winsound.PlaySound(
            self.path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
        )

    def tick(self) -> None:
        pass

    def stop(self) -> None:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)


class BellPlayer:
    """Universal fallback: the terminal bell, re-struck every tick."""

    def start(self) -> None:
        sys.stdout.write("\a")
        sys.stdout.flush()

    def tick(self) -> None:
        self.start()

    def stop(self) -> None:
        pass


class SilentPlayer:
    """Used when sound is disabled in config."""

    def start(self) -> None:
        pass

    def tick(self) -> None:
        pass

    def stop(self) -> None:
        pass


# While ringing, never let more than this pass between strikes of the sound.
RING_PERIOD = 0.9


def _file_player(path: str, period: float | None = None):
    if sys.platform == "darwin" and shutil.which("afplay"):
        return SubprocessPlayer(["afplay", path], period=period)
    if sys.platform.startswith("win"):
        try:
            import winsound  # noqa: F401

            return WinsoundPlayer(path)
        except ImportError:
            pass
    for cmd, extra in (("paplay", []), ("aplay", ["-q"]), ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"])):
        if shutil.which(cmd):
            return SubprocessPlayer([cmd, *extra, path], period=period)
    return BellPlayer()


def make_player(spec: str, cfg: Config, insistent: bool = False):
    """Best available player for a sound spec (honors sound_enabled).

    insistent=True is for actual rings: short sounds are re-struck on a tight
    period so the alarm sounds continuous. Previews play naturally.
    """
    if not cfg.sound_enabled:
        return SilentPlayer()
    path = resolve_sound_path(spec, cfg)
    if path is None:
        return BellPlayer()
    return _file_player(path, period=RING_PERIOD if insistent else None)


def test_sound(spec: str, cfg: Config, seconds: float = 2.0) -> int:
    """`alarm test-sound`: play the spec briefly so the user can hear it."""
    import dataclasses

    player = make_player(spec, dataclasses.replace(cfg, sound_enabled=True))
    kind = type(player).__name__
    print(f"playing {spec!r} via {kind} for {seconds:g}s ...")
    player.start()
    time.sleep(seconds)
    player.stop()
    return 0
