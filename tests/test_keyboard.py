import time

from betteralarm import keyboard


class TestNormalize:
    def test_letters_lowercased(self):
        assert keyboard.normalize("S") == "s"
        assert keyboard.normalize("q") == "q"

    def test_enter_variants(self):
        assert keyboard.normalize("\r") == "enter"
        assert keyboard.normalize("\n") == "enter"

    def test_ctrl_c_raises(self):
        import pytest

        with pytest.raises(KeyboardInterrupt):
            keyboard.normalize("\x03")

    def test_other_control_chars_dropped(self):
        assert keyboard.normalize("\x1b") is None
        assert keyboard.normalize("\x00") is None


class TestNullKeyboard:
    def test_waits_timeout_and_returns_none(self):
        kb = keyboard.NullKeyboard()
        with kb:
            start = time.monotonic()
            assert kb.get_key(0.05) is None
            assert time.monotonic() - start >= 0.04


class TestPosixEscapeDrain:
    """A CSI sequence split across reads (SSH latency) must not leak fake keypresses."""

    def make_kb(self, batches):
        # batches: list of (delay_in_polls, bytes) — bytes become readable only
        # after that many _wait_readable calls, simulating network latency
        kb = keyboard.PosixKeyboard.__new__(keyboard.PosixKeyboard)
        kb._fd = 0
        pending = [[delay, list(data)] for delay, data in batches]

        def fake_wait(timeout):
            if not pending:
                return False
            if pending[0][0] > 0:
                pending[0][0] -= 1
                return False
            return bool(pending[0][1])

        def fake_read():
            ch = pending[0][1].pop(0)
            if not pending[0][1]:
                pending.pop(0)
            return chr(ch)

        kb._wait_readable = fake_wait
        kb._read_char = fake_read
        return kb

    def test_intact_escape_sequence_swallowed(self):
        kb = self.make_kb([(0, b"\x1b[D")])
        assert kb.get_key(0.1) is None

    def test_split_escape_sequence_swallowed(self):
        # ESC arrives alone; '[D' lands one poll later (SSH latency) — must still
        # be eaten, not returned as a fake 'd' that would dismiss a ringing alarm
        kb = self.make_kb([(0, b"\x1b"), (1, b"[D")])
        assert kb.get_key(0.1) is None

    def test_real_key_typed_later_still_works(self):
        kb = self.make_kb([(0, b"\x1b"), (1, b"[D"), (6, b"s")])
        assert kb.get_key(0.1) is None  # escape sequence fully swallowed
        key = None
        for _ in range(8):
            key = kb.get_key(0.1)
            if key:
                break
        assert key == "s"


def test_open_keyboard_non_tty(monkeypatch):
    monkeypatch.setattr(keyboard.sys.stdin, "isatty", lambda: False)
    assert isinstance(keyboard.open_keyboard(), keyboard.NullKeyboard)
