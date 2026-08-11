import json
from datetime import datetime

from betteralarm.config import Config, data_path
from betteralarm.models import Alarm
from betteralarm.store import SCHEMA_VERSION, AppState, Store, find_alarm
from betteralarm.errors import UserError

import pytest


def make_alarm(**kw):
    defaults = dict(id="a1b2c3d4", label="tea", type="once", at=datetime(2026, 8, 11, 16, 5))
    return Alarm(**(defaults | kw))


class TestStore:
    def test_load_missing_file_gives_fresh_state(self):
        state = Store().load()
        assert state.alarms == []
        assert state.config == Config()
        assert state.version == SCHEMA_VERSION

    def test_roundtrip(self):
        store = Store()
        state = AppState(config=Config(snooze_minutes=4), alarms=[make_alarm()])
        store.save(state)
        loaded = store.load()
        assert loaded == state

    def test_save_creates_directory(self):
        Store().save(AppState(config=Config(), alarms=[]))
        assert data_path().exists()

    def test_save_is_pretty_json(self):
        Store().save(AppState(config=Config(), alarms=[make_alarm()]))
        text = data_path().read_text()
        doc = json.loads(text)
        assert doc["version"] == SCHEMA_VERSION
        assert "\n" in text  # indented, human-editable

    def test_corrupt_file_quarantined(self, capsys):
        data_path().parent.mkdir(parents=True)
        data_path().write_text("{not json")
        state = Store().load()
        assert state.alarms == []
        quarantined = list(data_path().parent.glob("*.corrupt-*"))
        assert len(quarantined) == 1
        assert "corrupt" in capsys.readouterr().err.lower()

    def test_wrong_root_type_quarantined(self, capsys):
        data_path().parent.mkdir(parents=True)
        data_path().write_text('["a", "list"]')
        assert Store().load().alarms == []
        assert list(data_path().parent.glob("*.corrupt-*"))

    def test_single_bad_alarm_skipped(self, capsys):
        store = Store()
        store.save(AppState(config=Config(), alarms=[make_alarm()]))
        doc = json.loads(data_path().read_text())
        doc["alarms"].append({"garbage": True})
        data_path().write_text(json.dumps(doc))
        state = store.load()
        assert len(state.alarms) == 1
        assert "skip" in capsys.readouterr().err.lower()

    def test_migration_hook_runs(self):
        from betteralarm import store as store_mod

        data_path().parent.mkdir(parents=True)
        data_path().write_text(json.dumps({"version": 0, "alarms": [], "config": {}}))
        called = {}

        def migrate_v0(doc):
            called["yes"] = True
            doc["version"] = 1
            return doc

        old = dict(store_mod.MIGRATIONS)
        store_mod.MIGRATIONS[0] = migrate_v0
        try:
            state = Store().load()
        finally:
            store_mod.MIGRATIONS.clear()
            store_mod.MIGRATIONS.update(old)
        assert called.get("yes")
        assert state.version == SCHEMA_VERSION

    def test_mtime_tracks_saves(self):
        store = Store()
        assert store.mtime() is None
        store.save(AppState(config=Config(), alarms=[]))
        assert store.mtime() is not None


class TestFindAlarm:
    def state(self):
        return AppState(
            config=Config(),
            alarms=[
                make_alarm(id="a1b2c3d4", label="tea"),
                make_alarm(id="a9f8e7d6", label="standup"),
            ],
        )

    def test_by_id_prefix(self):
        assert find_alarm(self.state(), "a1b2").id == "a1b2c3d4"

    def test_by_label(self):
        assert find_alarm(self.state(), "standup").id == "a9f8e7d6"

    def test_ambiguous_prefix_raises(self):
        with pytest.raises(UserError, match="matches"):
            find_alarm(self.state(), "a")

    def test_missing_raises(self):
        with pytest.raises(UserError, match="no alarm"):
            find_alarm(self.state(), "nope")

    def test_label_wins_over_short_prefix(self):
        state = self.state()
        state.alarms[0].label = "a"
        assert find_alarm(state, "a").label == "a"
