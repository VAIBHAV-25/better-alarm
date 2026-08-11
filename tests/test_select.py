"""The arrow-key selector (❯), driven by an injected key stream."""

import pytest

from betteralarm.interactive import Cancelled, select


def test_enter_picks_first_by_default(capsys):
    assert select("Q?", ["a", "b"], keys=iter(["enter"])) == 0


def test_down_moves_selection():
    assert select("Q?", ["a", "b", "c"], keys=iter(["down", "down", "enter"])) == 2


def test_wraps_around():
    assert select("Q?", ["a", "b", "c"], keys=iter(["up", "enter"])) == 2
    assert select("Q?", ["a", "b"], keys=iter(["down", "down", "enter"])) == 0


def test_esc_cancels():
    with pytest.raises(Cancelled):
        select("Q?", ["a"], keys=iter(["esc"]))


def test_renders_pointer_and_all_options(capsys):
    select("Which?", ["wake", "tea"], keys=iter(["enter"]))
    out = capsys.readouterr().out
    assert "❯" in out
    assert "wake" in out and "tea" in out


def test_number_key_jumps_and_picks():
    assert select("Q?", ["a", "b", "c"], keys=iter(["2"])) == 1


def test_options_can_carry_descriptions(capsys):
    # (label, description) tuples render as two aligned columns
    idx = select(
        "Q?",
        [("Set an alarm", "wake up at a time"), ("Quit", "leave the shell")],
        keys=iter(["enter"]),
    )
    assert idx == 0
    out = capsys.readouterr().out
    assert "Set an alarm" in out
    assert "wake up at a time" in out
    assert "leave the shell" in out


def test_numbered_fallback_shows_descriptions(capsys):
    from betteralarm.interactive import pick

    def scripted(prompt=""):
        return "1"

    pick("Q?", [("Set an alarm", "wake up at a time")], input_fn=scripted)
    assert "wake up at a time" in capsys.readouterr().out
