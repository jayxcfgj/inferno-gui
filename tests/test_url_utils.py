# tests/test_url_utils.py
"""URL helper: external links and config files open in the invoking
user's desktop session, not in root's.

The GUI runs as root (PTP hardware timestamping needs it), so
QDesktopServices.openUrl launches a browser in root's environment
(HOME=/root, no session bus) and silently discards the boolean result.
open_url_as_user() delegates to `sudo -u <user> xdg-open <url>` — the
pattern that already works for control_tab's NetAudio launcher — and
forwards the user's session environment (run_gui.sh exports it before
sudo'ing the GUI).

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_url_utils.py -v
"""
import logging
import os
import pwd
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication

from inferno_gui.core.config import get_actual_user_home
from inferno_gui.ui.url_utils import open_url_as_user

# PyQt hält keine Referenz auf die QApplication: wird der Python-Wrapper
# garbage-collected, zerstört Qt die App samt aller Widgets. Deshalb die
# Referenz modulglobal halten (Muster tests/test_sync_icons.py).
_APP = None


def _get_app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture
def qt_offscreen():
    """QApplication bereitstellen (modulglobal gehalten)."""
    return _get_app()


def _capture_start_detached(monkeypatch, ok=True):
    """QProcess.startDetached (Member-Form) patchen und jeden Aufruf
    mitschneiden.

    Liefert eine Liste von (program, arguments, env-dict)-Tupeln; das
    env-dict spiegelt die QProcessEnvironment, die der Helfer für den
    Kind-Prozess gesetzt hat (alles, was sudo sehen soll).
    """
    captured = []

    def fake_start_detached(proc):
        qenv = proc.processEnvironment()
        captured.append((
            proc.program(),
            list(proc.arguments()),
            {key: qenv.value(key) for key in qenv.keys()},
        ))
        return ok

    monkeypatch.setattr(QProcess, "startDetached", fake_start_detached)
    return captured


def _fake_settings_home(monkeypatch, tmp_path):
    """SettingsTab auf ein Fake-Home umleiten (SUDO-Kontext nachbilden:
    Path.home() wäre /root, get_actual_user_home() das echte Home)."""
    import inferno_gui.ui.settings_tab as settings_tab_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(settings_tab_mod, "get_actual_user_home", lambda: fake_home)
    # Hermetisch: keine echten `ip`-Aufrufe beim Konstruieren des Tabs.
    monkeypatch.setattr(settings_tab_mod, "get_available_interfaces", lambda: ["eth0"])
    monkeypatch.setattr(settings_tab_mod, "get_interface_ip",
                        lambda iface: "10.0.0.1")
    return fake_home


# ── (a) Kommando + Session-Env ────────────────────────────────────
def test_builds_sudo_command_with_session_env(qt_offscreen, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "jacob")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.delenv("DISPLAY", raising=False)

    captured = _capture_start_detached(monkeypatch)
    url = "https://github.com/teodly/inferno"
    open_url_as_user(url)

    assert len(captured) == 1, "exactly one detached launch per call"
    program, args, env = captured[0]
    assert program == "sudo"
    assert args == ["-u", "jacob", "xdg-open", url]
    # Session-Env wird weitergereicht — aber nur die gesetzten Session-Keys
    assert env.get("XDG_RUNTIME_DIR") == "/run/user/1000"
    assert env.get("DBUS_SESSION_BUS_ADDRESS") == "unix:path=/run/user/1000/bus"
    assert "DISPLAY" not in env, "unset session keys must not be forwarded"


# ── (b) User-Auflösung ohne SUDO_USER ──────────────────────────────
def test_falls_back_without_sudo_user(qt_offscreen, monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    captured = _capture_start_detached(monkeypatch)
    open_url_as_user("https://example.com/")

    owner = pwd.getpwuid(get_actual_user_home().stat().st_uid).pw_name
    _, args, _ = captured[0]
    assert args[0] == "-u"
    assert args[1] == owner, \
        "without SUDO_USER the target must be the owner of the actual user home"


# ── (c) Fehlgeschlagener Start bleibt ungefährlich ─────────────────
def test_start_detached_failure_is_safe(qt_offscreen, monkeypatch, caplog):
    monkeypatch.setenv("SUDO_USER", "jacob")
    _capture_start_detached(monkeypatch, ok=False)
    url = "https://example.com/no-such-page"

    with caplog.at_level(logging.WARNING, logger="inferno_gui.ui.url_utils"):
        open_url_as_user(url)  # darf nicht werfen

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a failed launch must log a warning"
    assert any(url in r.getMessage() for r in warnings), \
        "the warning must name the URL that failed to open"


# ── (d) Settings-Buttons lösen gegen das echte User-Home auf ──────
def test_open_pipe_wire_override_uses_user_home(qt_offscreen, monkeypatch, tmp_path):
    from inferno_gui.ui.settings_tab import SettingsTab

    fake_home = _fake_settings_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SUDO_USER", "jacob")

    st = SettingsTab()
    expected = fake_home / ".config/systemd/user/pipewire.service.d/override.conf"

    # Button-Ziel und Status-Check folgen dem echten User-Home (nicht
    # Path.home() = /root unter sudo)
    assert st._pw_override_path == expected
    assert st._asoundrc_path == fake_home / ".asoundrc"

    captured = _capture_start_detached(monkeypatch)
    st.pw_override_btn.click()
    assert len(captured) == 1
    program, args, _env = captured[0]
    assert program == "sudo"
    assert args[2] == "xdg-open"
    assert args[3] == str(expected), \
        "the button must open the user-home override file, not /root's"

    # Status-Check prüft dieselbe Datei, die der Button öffnet
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_text("[Service]\nSystemCallFilter=@clock\n")
    st._check_system_status()
    assert st.pw_override_status.text().startswith("✓"), \
        "status check must read the override via the actual user home"


def test_other_config_buttons_open_via_helper(qt_offscreen, monkeypatch, tmp_path):
    """PTPv1/PTPv2/asoundrc-Buttons gehen ebenfalls über den Helfer."""
    from inferno_gui.core.config import get_default_statime_config
    from inferno_gui.ui.settings_tab import SettingsTab

    fake_home = _fake_settings_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SUDO_USER", "jacob")

    st = SettingsTab()
    captured = _capture_start_detached(monkeypatch)

    for btn, path in (
        (st.ptpv1_btn, get_default_statime_config('v1')),
        (st.ptpv2_btn, get_default_statime_config('v2')),
        (st.asoundrc_btn, fake_home / ".asoundrc"),
    ):
        captured.clear()
        btn.click()
        assert len(captured) == 1, f"exactly one launch for {btn.text()}"
        program, args, _env = captured[0]
        assert program == "sudo"
        assert args[2] == "xdg-open"
        assert args[3] == str(path), \
            f"{btn.text()} must open {path} in the user's session"


def test_help_menu_opens_links_via_helper(qt_offscreen, monkeypatch):
    """Die GitHub-Links im Help-Menü laufen über den Helfer (nicht mehr
    über QDesktopServices im Root-Environment)."""
    from inferno_gui.ui.main_window import MainWindow

    monkeypatch.setenv("SUDO_USER", "jacob")
    mw = MainWindow()
    help_menu = next(a.menu() for a in mw.menuBar().actions() if a.text() == "Help")

    captured = _capture_start_detached(monkeypatch)
    for title, url in (
        ("Inferno GitHub", "https://github.com/teodly/inferno"),
        ("Statime GitHub", "https://github.com/teodly/statime"),
    ):
        captured.clear()
        action = next(a for a in help_menu.actions() if a.text() == title)
        action.trigger()
        assert len(captured) == 1, f"exactly one launch for {title}"
        program, args, _env = captured[0]
        assert program == "sudo"
        assert args[2] == "xdg-open"
        assert args[3] == url
    mw.hide()
