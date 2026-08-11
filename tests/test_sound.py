import pytest

from betteralarm import sound
from betteralarm.config import Config


class TestResolveSoundPath:
    def test_bell_is_none(self):
        assert sound.resolve_sound_path("bell", Config()) is None

    def test_default_follows_config(self):
        cfg = Config(default_sound="bell")
        assert sound.resolve_sound_path("default", cfg) is None

    def test_file_spec(self, tmp_path):
        wav = tmp_path / "ding.wav"
        wav.write_bytes(b"RIFF")
        assert sound.resolve_sound_path(f"file:{wav}", Config()) == str(wav)

    def test_missing_file_falls_back_to_bell(self, tmp_path, capsys):
        assert sound.resolve_sound_path("file:/nope/missing.wav", Config()) is None
        assert "fall" in capsys.readouterr().err.lower()

    def test_system_sound_mac(self, monkeypatch, tmp_path):
        glass = tmp_path / "Glass.aiff"
        glass.write_bytes(b"x")
        monkeypatch.setattr(sound, "_SYSTEM_SOUND_DIRS", [str(tmp_path)])
        assert sound.resolve_sound_path("system:Glass", Config()) == str(glass)

    def test_unknown_system_sound_falls_back(self, monkeypatch, capsys):
        monkeypatch.setattr(sound, "_SYSTEM_SOUND_DIRS", [])
        assert sound.resolve_sound_path("system:Nope", Config()) is None

    def test_sound_disabled_globally(self):
        cfg = Config(sound_enabled=False)
        player = sound.make_player("system:Glass", cfg)
        assert isinstance(player, sound.SilentPlayer)


class FakeProc:
    def __init__(self, exit_code=0):
        self.terminated = False
        self._done = False
        self._exit_code = exit_code

    def poll(self):
        return self._exit_code if self._done else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class TestSubprocessPlayer:
    def make(self, monkeypatch):
        spawned = []

        def fake_popen(cmd, **kw):
            proc = FakeProc()
            spawned.append(proc)
            return proc

        monkeypatch.setattr(sound.subprocess, "Popen", fake_popen)
        return sound.SubprocessPlayer(["afplay", "/x.aiff"]), spawned

    def test_start_spawns(self, monkeypatch):
        player, spawned = self.make(monkeypatch)
        player.start()
        assert len(spawned) == 1

    def test_tick_reloops_when_finished(self, monkeypatch):
        player, spawned = self.make(monkeypatch)
        player.start()
        player.tick()
        assert len(spawned) == 1  # still playing: no respawn
        spawned[0]._done = True
        player.tick()
        assert len(spawned) == 2  # finished: looped

    def test_stop_terminates(self, monkeypatch):
        player, spawned = self.make(monkeypatch)
        player.start()
        player.stop()
        assert spawned[0].terminated
        player.tick()
        assert len(spawned) == 1  # stopped players don't reloop

    def test_stop_without_start_is_safe(self, monkeypatch):
        player, _ = self.make(monkeypatch)
        player.stop()

    def test_repeatedly_failing_player_falls_back_to_bell(self, monkeypatch, capsys):
        # e.g. paplay present but PulseAudio down: instant nonzero exits must not
        # become an unbounded 4-per-second spawn loop with a silent alarm
        spawned = []

        def fake_popen(cmd, **kw):
            proc = FakeProc(exit_code=1)
            proc._done = True  # dies immediately
            spawned.append(proc)
            return proc

        monkeypatch.setattr(sound.subprocess, "Popen", fake_popen)
        player = sound.SubprocessPlayer(["paplay", "/x.wav"])
        player.start()
        for _ in range(10):
            player.tick()
        assert len(spawned) <= 3, "failing player must stop respawning"
        assert "\a" in capsys.readouterr().out, "must fall back to the bell"


class TestBellPlayer:
    def test_writes_bell(self, capsys):
        player = sound.BellPlayer()
        player.start()
        assert "\a" in capsys.readouterr().out

    def test_stop_is_noop(self):
        sound.BellPlayer().stop()


def test_make_player_bell(monkeypatch):
    player = sound.make_player("bell", Config())
    assert isinstance(player, sound.BellPlayer)


def test_test_sound_overrides_sound_disabled(capsys):
    # Explicitly previewing a sound should be audible even when sound is off.
    cfg = Config(sound_enabled=False, default_sound="bell")
    assert sound.test_sound("bell", cfg, seconds=0.01) == 0
    out = capsys.readouterr().out
    assert "SilentPlayer" not in out
    assert "\a" in out


class TestInsistentRing:
    def test_long_sound_is_restarted_after_the_period(self):
        # a ring must sound continuous: cap each play and strike again
        import time as _time

        player = sound.SubprocessPlayer(["sleep", "5"], period=0.05)
        player.start()
        first_pid = player.proc.pid
        _time.sleep(0.1)
        player.tick()
        assert player.proc.pid != first_pid
        player.stop()

    def test_make_player_wires_the_period_for_rings(self, tmp_path):
        f = tmp_path / "x.wav"
        f.write_bytes(b"")
        player = sound.make_player(f"file:{f}", Config(), insistent=True)
        if isinstance(player, sound.SubprocessPlayer):
            assert player.period is not None

    def test_preview_plays_naturally(self, tmp_path):
        f = tmp_path / "x.wav"
        f.write_bytes(b"")
        player = sound.make_player(f"file:{f}", Config())
        if isinstance(player, sound.SubprocessPlayer):
            assert player.period is None
