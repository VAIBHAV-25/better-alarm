import pytest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point every test at a throwaway data dir so ~/.better-alarm is never touched."""
    monkeypatch.setenv("BETTER_ALARM_HOME", str(tmp_path / "data"))
    return tmp_path / "data"
