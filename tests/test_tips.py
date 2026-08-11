"""Rotating one-line tips shown in friendly contexts."""

from datetime import date

from betteralarm import tips


def test_tip_is_deterministic_per_day():
    assert tips.daily_tip(date(2026, 8, 11)) == tips.daily_tip(date(2026, 8, 11))


def test_tip_rotates_across_days():
    seen = {tips.daily_tip(date(2026, 8, d)) for d in range(1, 29)}
    assert len(seen) > 1


def test_tip_at_offset_rotates_within_a_day():
    day = date(2026, 8, 11)
    seen = {tips.tip_at(day, n) for n in range(4)}
    assert len(seen) == 4  # consecutive actions get different tips


def test_tip_at_zero_matches_daily_tip():
    day = date(2026, 8, 11)
    assert tips.tip_at(day, 0) == tips.daily_tip(day)


def test_every_tip_is_a_short_single_line():
    assert tips.TIPS
    for tip in tips.TIPS:
        assert "\n" not in tip
        assert len(tip) < 100


def test_tips_speak_user_not_developer():
    # no environment variables, no pip, no internals — tips are for users
    for tip in tips.TIPS:
        assert "BETTER_ALARM_HOME" not in tip
        assert "pip " not in tip
