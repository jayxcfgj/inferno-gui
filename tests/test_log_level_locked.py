"""LogLevel is locked to TRACE: the log parser and PipeWire node automation
require trace level, so the combo is permanently disabled, load/save/reset
force TRACE, and set_running_state may never re-enable it.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_log_level_locked.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from inferno_gui.core.app_settings import user_settings

# Hold a module-level reference: a temporary QApplication() expression is
# garbage-collected immediately, which aborts later widget construction.
_app = QApplication.instance() or QApplication(sys.argv)

TOOLTIP = (
    "The log parser and PipeWire node automation require trace level; "
    "changing it would break status display and node creation."
)


def _ensure_app() -> QApplication:
    return _app


def _fake_interfaces(monkeypatch, ifaces, ips=None):
    """Force the detected interface list and IPs (same pattern as
    tests/test_interface_persistence.py)."""
    import inferno_gui.core.config as config
    import inferno_gui.ui.settings_tab as settings_tab
    ips = ips or {}
    monkeypatch.setattr(config, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(config, "get_interface_ip", lambda iface: ips.get(iface))
    monkeypatch.setattr(settings_tab, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(settings_tab, "get_interface_ip", lambda iface: ips.get(iface))


@pytest.fixture
def user_home(monkeypatch, tmp_path):
    """Redirect both get_actual_user_home references to a fresh fake home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import inferno_gui.core.app_settings as app_settings
    import inferno_gui.core.config as config
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(config, "get_actual_user_home", lambda: fake_home)
    settings = user_settings("control")
    settings.clear()
    settings.sync()
    return fake_home


@pytest.fixture
def silenced_dialogs(monkeypatch):
    """Make save/reset modal dialogs return immediately (offscreen tests)."""
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def _write_statime_templates() -> None:
    """Create statime config files shaped like the installer templates."""
    from inferno_gui.core.config import get_default_statime_config
    for ptp_ver in ("v1", "v2"):
        path = get_default_statime_config(ptp_ver)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[global]\n"
            'domain = 0\n'
            'interface = "eth0"\n'
            'log_level = "info"\n'
            "\n"
            "[[port]]\n"
            "sync_interval = 0\n"
            "announce_interval = 1\n"
        )


def test_log_level_disabled_after_construction(user_home, monkeypatch):
    """(a) The combo is disabled with an explanatory tooltip from the start."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    assert st.log_level.isEnabled() is False
    assert st.log_level.toolTip() == TOOLTIP
    assert st.log_level.currentText() == "TRACE"


def test_save_writes_trace(user_home, monkeypatch, silenced_dialogs):
    """(b) Saving always writes log_level = "trace" to the statime TOMLs,
    no matter what value the combo was programmatically forced to hold."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    from inferno_gui.core.config import get_default_statime_config
    from inferno_gui.ui.settings_tab import SettingsTab
    _write_statime_templates()
    st = SettingsTab()
    # Simulate tampering: enable and set a non-trace value.
    st.log_level.setEnabled(True)
    st.log_level.setCurrentText("DEBUG")

    st.save_settings()

    for ptp_ver in ("v1", "v2"):
        content = get_default_statime_config(ptp_ver).read_text()
        assert 'log_level = "trace"' in content, f"{ptp_ver}: {content}"
        assert 'log_level = "info"' not in content
        assert 'log_level = "debug"' not in content
        assert user_settings("control").value("log_level", "", type=str) == "TRACE"
        assert st.log_level.isEnabled() is False


def test_reset_returns_trace(user_home, monkeypatch, silenced_dialogs):
    """(c) Reset forces the combo back to TRACE (and keeps it disabled)."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    st.log_level.setEnabled(True)
    st.log_level.setCurrentText("DEBUG")

    st.reset_to_defaults()

    assert st.log_level.currentText() == "TRACE"
    assert st.log_level.isEnabled() is False


def test_running_state_leaves_log_level_disabled(user_home, monkeypatch):
    """(d) set_running_state toggles the other widgets but never re-enables
    log_level — in either direction, and across repeated calls."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()

    st.set_running_state(True)
    assert st.iface_combo.isEnabled() is False, "running must disable widgets"
    assert st.log_level.isEnabled() is False

    st.set_running_state(False)
    assert st.iface_combo.isEnabled() is True, "stopped must re-enable widgets"
    assert st.log_level.isEnabled() is False

    st.set_running_state(False)  # repeated call stays consistent
    assert st.iface_combo.isEnabled() is True
    assert st.log_level.isEnabled() is False

    st.set_running_state(True)
    assert st.iface_combo.isEnabled() is False
    assert st.log_level.isEnabled() is False


def test_load_forces_trace(user_home, monkeypatch):
    """load_settings never restores a stored non-trace level."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    settings = user_settings("control")
    settings.setValue("log_level", "DEBUG")
    settings.sync()
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    assert st.log_level.currentText() == "TRACE"
    assert st.log_level.isEnabled() is False
