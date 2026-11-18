"""LogLevel is locked to TRACE: the log parser and PipeWire node automation
require trace level, so the combo is permanently disabled, load/save/reset
force TRACE, and set_running_state may never re-enable it.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_log_level_locked.py -q
"""
import os
import sys
from pathlib import Path

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


INSTALLER = Path(__file__).resolve().parent.parent / "install_inferno.sh"

# The exact template text install_inferno.sh's create_statime_config()
# writes (heredoc body, byte for byte): a [global] section plus a
# [port] TABLE — not a [[port]] array.
INSTALLER_TEMPLATE_V1 = (
    "# statime PTPv1 configuration for Inferno\n"
    "# IEEE 1588-2002\n"
    "\n"
    "[global]\n"
    "domain = 0\n"
    'interface = "eth0"\n'
    'log_level = "trace"\n'
    "\n"
    "[port]\n"
    "sync_interval = 0\n"
    "announce_interval = 1\n"
    "announce_receipt_timeout = 3\n"
    'delay_mechanism = "E2E"\n'
)
INSTALLER_TEMPLATE_V2 = (
    "# statime PTPv2 configuration for Inferno\n"
    "# IEEE 1588-2008\n"
    "\n"
    "[global]\n"
    "domain = 0\n"
    'interface = "eth0"\n'
    'log_level = "trace"\n'
    "two_step_flag = true\n"
    "\n"
    "[port]\n"
    "sync_interval = 0\n"
    "announce_interval = 1\n"
    "announce_receipt_timeout = 3\n"
    'delay_mechanism = "E2E"\n'
)

# Hand-rolled / pre-installer shape: a [[port]] ARRAY of tables with
# underscore keys and a non-trace log level.
ARRAY_SHAPED_CONFIG = (
    "[global]\n"
    "domain = 0\n"
    'interface = "eth0"\n'
    'log_level = "info"\n'
    "\n"
    "[[port]]\n"
    "sync_interval = 0\n"
    "announce_interval = 1\n"
)


def test_fixture_is_the_installers_exact_template_text():
    """Guard: the embedded templates must match the installer's heredoc
    text byte for byte, so the save tests below really reproduce the
    files create_statime_config() writes on install."""
    content = INSTALLER.read_text(encoding="utf-8")
    assert INSTALLER_TEMPLATE_V1 in content, "v1 template drifted"
    assert INSTALLER_TEMPLATE_V2 in content, "v2 template drifted"


def _write_statime_configs(content: str) -> None:
    """Create both statime config files with the given template text."""
    from inferno_gui.core.config import get_default_statime_config
    for ptp_ver in ("v1", "v2"):
        path = get_default_statime_config(ptp_ver)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _write_installer_templates() -> None:
    """Create both statime config files with the installer's exact
    per-version [port]-table template text."""
    from inferno_gui.core.config import get_default_statime_config
    for ptp_ver, template in (("v1", INSTALLER_TEMPLATE_V1),
                              ("v2", INSTALLER_TEMPLATE_V2)):
        path = get_default_statime_config(ptp_ver)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template)


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
    no matter what value the combo was programmatically forced to hold —
    and on the installer's exact [port]-table templates the save really
    lands: domain/sync/announce reach the file, which keeps its [port]
    table shape, its key style and its untouched keys."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    import tomli
    from inferno_gui.core.config import get_default_statime_config
    from inferno_gui.ui.settings_tab import SettingsTab
    _write_installer_templates()
    st = SettingsTab()
    # Simulate tampering: enable and set a non-trace value.
    st.log_level.setEnabled(True)
    st.log_level.setCurrentText("DEBUG")
    # Distinctive advanced values: when the save silently skips the file
    # (the old port[0] KeyError path), these never reach the disk.
    st.ptp_domain.setValue(3)
    st.sync_interval.setValue(5)
    st.announce_interval.setValue(7)

    st.save_settings()

    for ptp_ver in ("v1", "v2"):
        content = get_default_statime_config(ptp_ver).read_text()
        assert 'log_level = "trace"' in content, f"{ptp_ver}: {content}"
        assert 'log_level = "info"' not in content
        assert 'log_level = "debug"' not in content
        # The advanced settings actually landed on disk...
        assert 'domain = 3' in content, f"{ptp_ver}: {content}"
        assert 'sync_interval = 5' in content, f"{ptp_ver}: {content}"
        assert 'announce_interval = 7' in content, f"{ptp_ver}: {content}"
        # ...the installer's untouched keys survive the rewrite...
        assert 'announce_receipt_timeout = 3' in content
        assert 'delay_mechanism = "E2E"' in content
        assert 'interface = "eth0"' in content
        # ...and the [port] table shape and key style are preserved.
        data = tomli.loads(content)
        assert isinstance(data["port"], dict), \
            "the installer's [port] table must not become a [[port]] array"
        assert data["port"]["sync_interval"] == 5
        assert data["port"]["announce_interval"] == 7
        assert set(data["port"]) == {
            "sync_interval", "announce_interval",
            "announce_receipt_timeout", "delay_mechanism",
        }
        assert data["global"]["domain"] == 3
        assert data["global"]["log_level"] == "trace"
        if ptp_ver == "v2":
            assert data["global"]["two_step_flag"] is True
    assert user_settings("control").value("log_level", "", type=str) == "TRACE"
    assert st.log_level.isEnabled() is False


def test_save_handles_array_shaped_port_configs(user_home, monkeypatch,
                                                 silenced_dialogs):
    """Compatibility: [[port]] array configs keep their array shape; the
    values land in the port's existing (underscore) keys — no duplicate
    hyphen keys are added — and log_level flips back to trace."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    import tomli
    from inferno_gui.core.config import get_default_statime_config
    from inferno_gui.ui.settings_tab import SettingsTab
    _write_statime_configs(ARRAY_SHAPED_CONFIG)
    st = SettingsTab()
    st.ptp_domain.setValue(4)
    st.sync_interval.setValue(6)
    st.announce_interval.setValue(-3)  # within the spinbox range (-7..7)

    st.save_settings()

    for ptp_ver in ("v1", "v2"):
        content = get_default_statime_config(ptp_ver).read_text()
        assert 'log_level = "trace"' in content, f"{ptp_ver}: {content}"
        data = tomli.loads(content)
        assert data["global"]["domain"] == 4
        assert data["global"]["log_level"] == "trace"
        # Still an array of tables; the existing keys are updated in place.
        assert isinstance(data["port"], list) and len(data["port"]) == 1
        assert data["port"][0] == {"sync_interval": 6, "announce_interval": -3}, \
            f"{ptp_ver}: {content}"


def test_port_shape_mismatch_still_saves(user_home, monkeypatch,
                                         silenced_dialogs):
    """A config whose port entry has an unexpected shape must not block
    the save: log_level and domain still land in the file."""
    _fake_interfaces(monkeypatch, ["eth0"])
    _ensure_app()
    from inferno_gui.core.config import get_default_statime_config
    from inferno_gui.ui.settings_tab import SettingsTab
    # Top-level scalar port: a shape no port update can handle — it must
    # not block the save of the other settings.
    _write_statime_configs(
        'port = 7\n\n[global]\ndomain = 0\nlog_level = "info"\n')
    st = SettingsTab()
    st.ptp_domain.setValue(9)

    st.save_settings()

    for ptp_ver in ("v1", "v2"):
        content = get_default_statime_config(ptp_ver).read_text()
        assert 'log_level = "trace"' in content, f"{ptp_ver}: {content}"
        assert 'domain = 9' in content, f"{ptp_ver}: {content}"


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
