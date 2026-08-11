"""ANSI styling that vanishes when output isn't a terminal (or NO_COLOR is set)."""

from betteralarm import colors


def test_plain_when_not_a_tty():
    # pytest's stdout is captured, not a tty → styling must be a no-op
    assert colors.style("hello", "bold", "cyan") == "hello"


def test_wraps_when_forced_on():
    styled = colors.style("hello", "bold", "cyan", when=True)
    assert styled.startswith("\x1b[") and styled.endswith("\x1b[0m")
    assert "hello" in styled


def test_multiple_codes_joined():
    assert colors.style("x", "bold", "green", when=True) == "\x1b[1;32mx\x1b[0m"


def test_no_color_env_wins(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert colors.enabled() is False


def test_force_color_env_enables(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert colors.enabled() is True
