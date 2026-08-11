from datetime import datetime, time, timedelta

import pytest

from betteralarm import timeparse


class TestParseTime:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("7:30", time(7, 30)),
            ("07:30", time(7, 30)),
            ("0730", time(7, 30)),
            ("730", time(7, 30)),
            ("7", time(7, 0)),
            ("23:59", time(23, 59)),
            ("0:00", time(0, 0)),
            ("7am", time(7, 0)),
            ("7AM", time(7, 0)),
            ("7:30pm", time(19, 30)),
            ("7.30pm", time(19, 30)),
            ("12am", time(0, 0)),
            ("12pm", time(12, 0)),
            ("12:30am", time(0, 30)),
            (" 7:30 ", time(7, 30)),
            ("6:03 pm", time(18, 3)),  # humans put a space before am/pm
            ("7 am", time(7, 0)),
        ],
    )
    def test_accepts(self, raw, expected):
        assert timeparse.parse_time(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["25:00", "7:60", "13pm", "0pm", "24:00", "abc", "", "7:3", "123456", "-1:00"],
    )
    def test_rejects(self, raw):
        with pytest.raises(ValueError):
            timeparse.parse_time(raw)

    def test_error_message_is_helpful(self):
        with pytest.raises(ValueError, match="7:30"):
            timeparse.parse_time("nope")


class TestParseDays:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("once", ()),
            ("daily", (0, 1, 2, 3, 4, 5, 6)),
            ("weekdays", (0, 1, 2, 3, 4)),
            ("weekends", (5, 6)),
            ("mon,wed,fri", (0, 2, 4)),
            ("MON,Wed", (0, 2)),
            ("tuesday", (1,)),
            ("sun", (6,)),
            ("fri,mon,fri", (0, 4)),
        ],
    )
    def test_accepts(self, raw, expected):
        assert timeparse.parse_days(raw) == expected

    @pytest.mark.parametrize("raw", ["", "someday", "mon,frx", "8"])
    def test_rejects(self, raw):
        with pytest.raises(ValueError):
            timeparse.parse_days(raw)


class TestParseDuration:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("25m", timedelta(minutes=25)),
            ("90s", timedelta(seconds=90)),
            ("1h", timedelta(hours=1)),
            ("1h30m", timedelta(hours=1, minutes=30)),
            ("1h 30m", timedelta(hours=1, minutes=30)),
            ("2h5m30s", timedelta(hours=2, minutes=5, seconds=30)),
            ("10", timedelta(minutes=10)),
            ("1.5h", timedelta(minutes=90)),
        ],
    )
    def test_accepts(self, raw, expected):
        assert timeparse.parse_duration(raw) == expected

    @pytest.mark.parametrize("raw", ["", "h", "5x", "-5m", "0", "0m", "m5"])
    def test_rejects(self, raw):
        with pytest.raises(ValueError):
            timeparse.parse_duration(raw)


class TestFormatDelta:
    @pytest.mark.parametrize(
        ("td", "expected"),
        [
            (timedelta(hours=15, minutes=41), "15h 41m"),
            (timedelta(minutes=3, seconds=20), "3m 20s"),
            (timedelta(days=2, hours=3), "2d 3h"),
            (timedelta(seconds=45), "45s"),
            (timedelta(minutes=59), "59m"),
            (timedelta(minutes=10, seconds=30), "10m"),
            (timedelta(hours=1), "1h 0m"),
            (timedelta(0), "now"),
        ],
    )
    def test_formats(self, td, expected):
        assert timeparse.format_delta(td) == expected


class TestFormatClock:
    def test_24h(self):
        assert timeparse.format_clock(datetime(2026, 8, 11, 16, 5, 33), "24") == "16:05:33"

    def test_12h(self):
        assert timeparse.format_clock(datetime(2026, 8, 11, 16, 5, 33), "12") == "4:05:33 PM"

    def test_12h_midnight(self):
        assert timeparse.format_clock(datetime(2026, 8, 11, 0, 5, 0), "12") == "12:05:00 AM"

    def test_no_seconds(self):
        assert timeparse.format_clock(datetime(2026, 8, 11, 9, 25), "24", seconds=False) == "09:25"

    def test_12h_no_seconds(self):
        assert timeparse.format_clock(datetime(2026, 8, 11, 19, 30), "12", seconds=False) == "7:30 PM"


class TestParseWhen:
    NOW = datetime(2026, 8, 11, 17, 0)  # a Tuesday, 5pm

    def when(self, raw):
        return timeparse.parse_when(raw, self.NOW)

    def test_tomorrow(self):
        assert self.when("tomorrow 9am") == datetime(2026, 8, 12, 9, 0)

    def test_tomorrow_with_at(self):
        assert self.when("tomorrow at 9:30") == datetime(2026, 8, 12, 9, 30)

    def test_today_future(self):
        assert self.when("today 23:15") == datetime(2026, 8, 11, 23, 15)

    def test_today_past_rejected(self):
        with pytest.raises(ValueError):
            self.when("today 7am")

    def test_weekday_next_occurrence(self):
        assert self.when("friday 7pm") == datetime(2026, 8, 14, 19, 0)

    def test_same_weekday_past_time_means_next_week(self):
        # it's Tuesday 5pm; "tuesday 9am" is next Tuesday
        assert self.when("tuesday 9am") == datetime(2026, 8, 18, 9, 0)

    def test_weekday_short_names(self):
        assert self.when("mon 8:00") == datetime(2026, 8, 17, 8, 0)

    def test_month_day(self):
        assert self.when("aug 20 14:00") == datetime(2026, 8, 20, 14, 0)

    def test_month_day_past_rolls_to_next_year(self):
        assert self.when("aug 1 9am") == datetime(2027, 8, 1, 9, 0)

    def test_full_month_name(self):
        assert self.when("december 25 8am") == datetime(2026, 12, 25, 8, 0)

    def test_day_word_without_time_rejected(self):
        with pytest.raises(ValueError):
            self.when("tomorrow")

    def test_nonsense_rejected_with_examples(self):
        with pytest.raises(ValueError, match="tomorrow"):
            self.when("someday maybe")
