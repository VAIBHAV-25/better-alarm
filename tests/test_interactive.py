"""The shared prompt toolkit: ask / pick / confirm, with scripted input."""

from datetime import time

import pytest

from betteralarm import interactive, timeparse
from betteralarm.interactive import Cancelled, ask, confirm, pick


def scripted(*lines):
    """An input_fn that replays canned answers, then EOFs like Ctrl-D."""
    replies = list(lines)

    def input_fn(prompt=""):
        if not replies:
            raise EOFError
        return replies.pop(0)

    return input_fn


class TestAsk:
    def test_returns_parsed_value(self):
        got = ask("Time?", parse=timeparse.parse_time, input_fn=scripted("7:30"))
        assert got == time(7, 30)

    def test_reprompts_on_invalid_then_accepts(self, capsys):
        got = ask("Time?", parse=timeparse.parse_time, input_fn=scripted("25:99", "7pm"))
        assert got == time(19, 0)
        assert "7:30" in capsys.readouterr().out  # error shows valid examples

    def test_empty_input_returns_default(self):
        got = ask("Label?", default="alarm", input_fn=scripted(""))
        assert got == "alarm"

    def test_empty_input_reprompts_when_no_default(self):
        got = ask("Time?", input_fn=scripted("", "7:30"))
        assert got == "7:30"

    def test_default_is_not_parsed(self):
        # default is already a value, not raw text to run through parse
        got = ask("Time?", default=time(9, 0), parse=timeparse.parse_time, input_fn=scripted(""))
        assert got == time(9, 0)

    def test_eof_raises_cancelled(self):
        with pytest.raises(Cancelled):
            ask("Time?", input_fn=scripted())


class TestPick:
    def test_returns_chosen_index(self):
        assert pick("Which?", ["wake", "tea"], input_fn=scripted("2")) == 1

    def test_reprompts_on_junk_and_out_of_range(self):
        assert pick("Which?", ["wake", "tea"], input_fn=scripted("x", "9", "1")) == 0

    def test_lists_every_option(self, capsys):
        pick("Which?", ["wake", "tea"], input_fn=scripted("1"))
        out = capsys.readouterr().out
        assert "1)" in out and "wake" in out
        assert "2)" in out and "tea" in out

    def test_eof_raises_cancelled(self):
        with pytest.raises(Cancelled):
            pick("Which?", ["wake"], input_fn=scripted())


class TestConfirm:
    def test_yes(self):
        assert confirm("Sure?", input_fn=scripted("y")) is True

    def test_no(self):
        assert confirm("Sure?", input_fn=scripted("n")) is False

    def test_empty_uses_default(self):
        assert confirm("Sure?", input_fn=scripted("")) is False
        assert confirm("Sure?", default=True, input_fn=scripted("")) is True


class TestPromptRules:
    """Input happens between two full-width horizontal rules."""

    def test_ask_frames_input_with_rules(self, capsys):
        ask("Time?", input_fn=scripted("7"))
        out = capsys.readouterr().out
        assert "Time?" in out
        assert "─" * 20 in out  # full-width rules above and below
        assert "╭" not in out  # no box corners

    def test_prompt_is_the_pointer(self):
        prompts = []

        def input_fn(prompt=""):
            prompts.append(prompt)
            return "x"

        ask("Q", input_fn=input_fn)
        assert "❯" in prompts[0]

    def test_confirm_framed_too(self, capsys):
        confirm("Sure?", input_fn=scripted("y"))
        out = capsys.readouterr().out
        assert "Sure? [y/N]" in out
        assert "─" * 20 in out

    def test_typing_back_cancels_an_ask(self):
        with pytest.raises(Cancelled):
            ask("Time?", input_fn=scripted("back"))

    def test_typing_cancel_cancels_a_confirm(self):
        with pytest.raises(Cancelled):
            confirm("Sure?", input_fn=scripted("cancel"))

    def test_typing_back_cancels_a_numbered_pick(self):
        with pytest.raises(Cancelled):
            pick("Q?", ["a", "b"], input_fn=scripted("back"))


class TestSelectHints:
    def test_select_shows_key_hints(self, capsys):
        from betteralarm.interactive import select

        select("Q?", ["a"], keys=iter(["enter"]))
        out = capsys.readouterr().out
        assert "↑/↓" in out and "Esc" in out

    def test_numbered_pick_shows_hint(self, capsys):
        pick("Q?", ["a", "b"], input_fn=scripted("1"))
        assert "number" in capsys.readouterr().out.lower()


class TestIsInteractive:
    def test_false_under_pytest(self):
        # pytest's stdin is not a TTY, so prompting must be off by default
        assert interactive.is_interactive() is False
