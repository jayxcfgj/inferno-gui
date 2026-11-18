"""Interface persistence: the last-used interface survives refreshes and
all application settings live in the invoking user's home directory (not
/root/.config when the GUI runs under sudo).

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_interface_persistence.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import QApplication

from inferno_gui.core.app_settings import user_settings


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def user_home(monkeypatch, tmp_path):
    """Redirect user_settings() to a fresh fake home directory."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import inferno_gui.core.app_settings as app_settings
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    settings = user_settings("control")
    settings.clear()
    settings.sync()
    return fake_home


def _fake_interfaces(monkeypatch, ifaces, ips=None):
    """Force the detected interface list and IPs for both tabs.

    control_tab imports the helpers from inferno_gui.core.config at call
    time; settings_tab bound them at module import. Both references must
    be patched.
    """
    import inferno_gui.core.config as config
    import inferno_gui.ui.settings_tab as settings_tab
    ips = ips or {}
    monkeypatch.setattr(config, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(config, "get_interface_ip", lambda iface: ips.get(iface))
    monkeypatch.setattr(settings_tab, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(settings_tab, "get_interface_ip", lambda iface: ips.get(iface))


def test_saved_interface_survives_refresh(monkeypatch, user_home):
    """(a) The saved interface is applied when the combo is populated."""
    settings = user_settings("control")
    settings.setValue("selected_interface", "eth1")
    settings.sync()
    _fake_interfaces(monkeypatch, ["eth0", "eth1"], {"eth0": "10.0.0.1", "eth1": "10.0.0.2"})

    app = _ensure_app()
    from inferno_gui.ui.control_tab import ControlTab
    ct = ControlTab()
    for _ in range(6):  # pattern from tests/test_layout_smoke.py:170
        app.processEvents()

    assert ct.interface_combo.currentData() == "eth1"

    # A later refresh (showEvent / refresh button) must keep the selection.
    ct._refresh_interfaces()
    for _ in range(6):
        app.processEvents()
    assert ct.interface_combo.currentData() == "eth1"


def test_refresh_does_not_clobber(monkeypatch, user_home):
    """(b) A saved interface missing from the list must not be overwritten."""
    settings = user_settings("control")
    settings.setValue("selected_interface", "eth9")
    settings.sync()
    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "10.0.0.1"})

    app = _ensure_app()
    from inferno_gui.ui.control_tab import ControlTab
    ct = ControlTab()
    for _ in range(6):
        app.processEvents()

    # Combo falls back to eth0, but the stored value must survive untouched.
    assert ct.interface_combo.currentData() == "eth0"
    stored = user_settings("control").value("selected_interface", "", type=str)
    assert stored == "eth9"


def test_user_settings_path():
    """(c) Settings live under the actual user's home, in InfernoGUI/<scope>.conf."""
    from inferno_gui.core import app_settings
    home = app_settings.get_actual_user_home()
    settings = app_settings.user_settings("control")
    assert Path(settings.fileName()) == home / ".config" / "InfernoGUI" / "control.conf"


def test_settings_tab_restores_after_populate(monkeypatch, user_home):
    """(d) SettingsTab populates its combo (in _init_ui) before load_settings reads."""
    settings = user_settings("control")
    settings.setValue("selected_interface", "eth1")
    settings.sync()
    _fake_interfaces(monkeypatch, ["eth0", "eth1"], {"eth0": "10.0.0.1", "eth1": "10.0.0.2"})

    app = _ensure_app()
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    for _ in range(6):
        app.processEvents()

    assert st.iface_combo.currentData() == "eth1"
