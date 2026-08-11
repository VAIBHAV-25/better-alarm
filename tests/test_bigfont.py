from betteralarm import bigfont


def test_all_glyphs_are_five_uniform_rows():
    for ch, rows in bigfont.FONT.items():
        assert len(rows) == 5, f"glyph {ch!r} must have 5 rows"
        assert len({len(r) for r in rows}) == 1, f"glyph {ch!r} rows must be uniform width"


def test_digits_and_colon_present():
    assert set("0123456789: ") <= set(bigfont.FONT)


def test_render_known_glyph():
    one = bigfont.FONT["1"]
    colon = bigfont.FONT[":"]
    rendered = bigfont.render_big("1:1")
    assert len(rendered) == 5
    for i in range(5):
        assert rendered[i] == f"{one[i]} {colon[i]} {one[i]}"


def test_render_unknown_char_becomes_space():
    assert bigfont.render_big("x") == bigfont.render_big(" ")


def test_ascii_fallback_char():
    rendered = bigfont.render_big("8", char="#")
    assert "#" in rendered[0]
    assert "█" not in "".join(rendered)


def test_width_matches_render():
    text = "12:34:56"
    assert bigfont.width(text) == len(bigfont.render_big(text)[0])
