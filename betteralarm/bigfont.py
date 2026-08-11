"""A hand-rolled 5-row block-glyph font for the big clock. Zero dependencies."""

from __future__ import annotations

FONT: dict[str, list[str]] = {
    "0": ["█████",
          "█   █",
          "█   █",
          "█   █",
          "█████"],
    "1": ["  █  ",
          " ██  ",
          "  █  ",
          "  █  ",
          " ███ "],
    "2": ["█████",
          "    █",
          "█████",
          "█    ",
          "█████"],
    "3": ["█████",
          "    █",
          " ████",
          "    █",
          "█████"],
    "4": ["█   █",
          "█   █",
          "█████",
          "    █",
          "    █"],
    "5": ["█████",
          "█    ",
          "█████",
          "    █",
          "█████"],
    "6": ["█████",
          "█    ",
          "█████",
          "█   █",
          "█████"],
    "7": ["█████",
          "    █",
          "   █ ",
          "  █  ",
          "  █  "],
    "8": ["█████",
          "█   █",
          "█████",
          "█   █",
          "█████"],
    "9": ["█████",
          "█   █",
          "█████",
          "    █",
          "█████"],
    ":": ["  ",
          "█ ",
          "  ",
          "█ ",
          "  "],
    # A/P/M so the 12-hour clock's am/pm suffix renders instead of vanishing
    "A": ["█████",
          "█   █",
          "█████",
          "█   █",
          "█   █"],
    "P": ["█████",
          "█   █",
          "█████",
          "█    ",
          "█    "],
    "M": ["█   █",
          "██ ██",
          "█ █ █",
          "█   █",
          "█   █"],
    " ": ["  ",
          "  ",
          "  ",
          "  ",
          "  "],
}

_GAP = " "


def render_big(text: str, char: str = "█") -> list[str]:
    """Render text as 5 lines of block glyphs; unknown characters become spaces."""
    glyphs = [FONT.get(ch, FONT[" "]) for ch in text]
    rows = [_GAP.join(g[row] for g in glyphs) for row in range(5)]
    if char != "█":
        rows = [r.replace("█", char) for r in rows]
    return rows


def width(text: str) -> int:
    return len(render_big(text)[0]) if text else 0
