"""Desktop notifications on ring: right command per platform, safe quoting."""

from betteralarm import notify
from betteralarm.config import Config


class TestNotificationCommand:
    def test_macos_uses_osascript(self, monkeypatch):
        monkeypatch.setattr(notify.sys, "platform", "darwin")
        monkeypatch.setattr(notify.shutil, "which", lambda c: "/usr/bin/" + c)
        cmd = notify.notification_command("⏰ tea", "ringing now")
        assert cmd[0] == "osascript"
        assert "ringing now" in cmd[-1] and "⏰ tea" in cmd[-1]

    def test_macos_quotes_are_escaped(self, monkeypatch):
        # a label like  say "hi"  must not break out of the AppleScript string
        monkeypatch.setattr(notify.sys, "platform", "darwin")
        monkeypatch.setattr(notify.shutil, "which", lambda c: "/usr/bin/" + c)
        cmd = notify.notification_command('say "hi"', "x")
        assert '\\"hi\\"' in cmd[-1]

    def test_linux_uses_notify_send(self, monkeypatch):
        monkeypatch.setattr(notify.sys, "platform", "linux")
        monkeypatch.setattr(
            notify.shutil, "which", lambda c: "/usr/bin/notify-send" if c == "notify-send" else None
        )
        cmd = notify.notification_command("t", "m")
        assert cmd == ["notify-send", "t", "m"]

    def test_no_backend_returns_none(self, monkeypatch):
        monkeypatch.setattr(notify.sys, "platform", "linux")
        monkeypatch.setattr(notify.shutil, "which", lambda c: None)
        assert notify.notification_command("t", "m") is None


def test_config_has_notifications_flag():
    assert Config().notifications is True
