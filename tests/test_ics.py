"""Minimal .ics parsing: enough to turn calendar events into alarms."""

from datetime import datetime

from betteralarm import cli
from betteralarm.ics import parse_ics

NOW = datetime(2026, 8, 11, 12, 0)

SAMPLE = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Team standup
DTSTART:20260812T091500
END:VEVENT
BEGIN:VEVENT
SUMMARY:Old meeting
DTSTART:20200101T100000
END:VEVENT
BEGIN:VEVENT
SUMMARY:All day thing
DTSTART;VALUE=DATE:20260813
END:VEVENT
BEGIN:VEVENT
SUMMARY:Folded across
  lines meeting
DTSTART:20260814T140000
END:VEVENT
END:VCALENDAR
"""


def test_future_timed_events_only():
    events = parse_ics(SAMPLE, NOW)
    names = [s for s, _ in events]
    assert "Team standup" in names
    assert "Old meeting" not in names  # past
    assert "All day thing" not in names  # no time of day


def test_folded_lines_unfold():
    events = dict(parse_ics(SAMPLE, NOW))
    assert "Folded across lines meeting" in events


def test_datetimes_parsed():
    events = dict(parse_ics(SAMPLE, NOW))
    assert events["Team standup"] == datetime(2026, 8, 12, 9, 15)


def test_import_command_creates_alarms(tmp_path, capsys):
    import json
    from betteralarm.config import data_path

    f = tmp_path / "cal.ics"
    f.write_text(SAMPLE.replace("20260812", "20990812").replace("20260814", "20990814"))
    assert cli.main(["import", str(f)]) == 0
    doc = json.loads(data_path().read_text())
    labels = {a["label"] for a in doc["alarms"]}
    assert "Team standup" in labels
    assert "imported 2" in capsys.readouterr().out


def test_import_with_lead_time(tmp_path):
    import json
    from betteralarm.config import data_path

    f = tmp_path / "cal.ics"
    f.write_text(SAMPLE.replace("20260812", "20990812").replace("20260814", "20990814"))
    assert cli.main(["import", str(f), "--before", "10"]) == 0
    doc = json.loads(data_path().read_text())
    standup = next(a for a in doc["alarms"] if a["label"] == "Team standup")
    assert standup["at"].endswith("T09:05:00")
