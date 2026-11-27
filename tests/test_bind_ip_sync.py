# tests/test_bind_ip_sync.py
"""BIND_IP in ~/.asoundrc follows the NIC's current IP (production fix).

Field report (verified by the user in the field): the system had a
static IP, production uses DHCP. After switching the NIC to DHCP and
reconnecting, the NIC got a new IP. The GUI (restarted) DISPLAYED the
new IP correctly (live read via get_interface_ip) but .asoundrc still
held the OLD static BIND_IP — no Dante connectivity. Re-selecting the
NIC and "Save Configuration" did NOT fix it (save_settings never
derived bind_ip from the interface); only a manual config edit did.

Contract (user-approved design):
- core.config.sync_bind_ip(interface, config=None): sets the pending
  config's bind_ip to get_interface_ip(interface); writes .asoundrc
  ONLY when the value actually differs; on success logs
  "Updated BIND_IP in ~/.asoundrc: <old> -> <new>"; when the interface
  has no usable IP (None/empty) it keeps the stored value and logs a
  warning ("interface <x> has no IP — keeping BIND_IP <old>").
- Called at three points: (a) settings_tab.save_settings() before
  persisting, (b) a GENUINE user interface-selection change in the
  settings tab (programmatic restores stay silent), (c) PTP start in
  the control tab — covers a DHCP change while the GUI was closed,
  silent except the log line (no popup).
- Ownership: the write goes through InfernoConfig.save(), whose
  chown_to_invoking_user keeps the invoking-user end state.

Run: QT_QPA_PLATFORM=offscreen uv run --no-project --with pytest \
    --with PyQt6 --with tomli --with tomli-w \
    python -m pytest tests/test_bind_ip_sync.py -q
"""
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication, QMessageBox

# Module-level QApplication reference (pattern tests/test_settings_latency.py):
# a temporary QApplication() expression is garbage-collected immediately.
_app = QApplication.instance() or QApplication(sys.argv)

ASOUNDRC_STALE = """pcm.inferno {
    type inferno

    NAME "FieldCard"
    SAMPLE_RATE "48000"

    TX_CHANNELS 16
    RX_CHANNELS 16

    BIND_IP "192.168.1.10"
    RX_LATENCY_NS 5000000
    TX_LATENCY_NS 8000000
}
"""


@pytest.fixture
def user_home(monkeypatch, tmp_path):
    """Redirect both get_actual_user_home references to a fresh fake home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import inferno_gui.core.app_settings as app_settings
    import inferno_gui.core.config as config
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(config, "get_actual_user_home", lambda: fake_home)
    settings = app_settings.user_settings("control")
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


def _fake_interfaces(monkeypatch, ifaces, ips=None):
    """Force the detected interface list and IPs (pattern from
    tests/test_settings_latency.py). Both module references are
    patched: sync_bind_ip resolves get_interface_ip via
    inferno_gui.core.config."""
    import inferno_gui.core.config as config
    import inferno_gui.ui.settings_tab as settings_tab
    ips = ips or {}
    monkeypatch.setattr(config, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(config, "get_interface_ip", lambda iface: ips.get(iface))
    monkeypatch.setattr(settings_tab, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(settings_tab, "get_interface_ip", lambda iface: ips.get(iface))


def _settings_tab(monkeypatch, home, asoundrc=None, ifaces=None, ips=None):
    """Build a SettingsTab against the fake home (optionally seeded)."""
    _fake_interfaces(monkeypatch, ifaces or ["eth0"], ips or {})
    if asoundrc is not None:
        (home / ".asoundrc").write_text(asoundrc)
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    _app.processEvents()
    return st


# ── core helper: sync_bind_ip ─────────────────────────────────────────


def test_sync_rewrites_stale_bind_ip(user_home, monkeypatch, caplog):
    """Old BIND_IP in .asoundrc, interface now has a different IP:
    sync sets the new value, every other key survives the rewrite,
    and the change is logged (info, English)."""
    (user_home / ".asoundrc").write_text(ASOUNDRC_STALE)
    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "10.0.0.9"})

    from inferno_gui.core.config import sync_bind_ip

    with caplog.at_level(logging.INFO, logger="inferno_gui.core.config"):
        changed = sync_bind_ip("eth0")

    assert changed is True
    content = (user_home / ".asoundrc").read_text()
    assert 'BIND_IP "10.0.0.9"' in content, content
    # every other key survives the regeneration
    assert 'NAME "FieldCard"' in content, content
    assert 'SAMPLE_RATE "48000"' in content, content
    assert "TX_CHANNELS 16" in content, content
    assert "RX_CHANNELS 16" in content, content
    assert "RX_LATENCY_NS 5000000" in content, content
    assert "TX_LATENCY_NS 8000000" in content, content
    assert ("Updated BIND_IP in ~/.asoundrc: 192.168.1.10 -> 10.0.0.9"
            in caplog.text), caplog.text


def test_sync_without_interface_ip_keeps_stored_bind_ip(
        user_home, monkeypatch, caplog):
    """Interface has no usable IP (None): keep the old BIND_IP, write
    nothing, log a warning that names the kept value."""
    (user_home / ".asoundrc").write_text(ASOUNDRC_STALE)
    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": None})

    from inferno_gui.core.config import sync_bind_ip

    with caplog.at_level(logging.WARNING, logger="inferno_gui.core.config"):
        changed = sync_bind_ip("eth0")

    assert changed is False
    content = (user_home / ".asoundrc").read_text()
    assert 'BIND_IP "192.168.1.10"' in content, content
    assert "Updated BIND_IP" not in caplog.text
    assert "has no IP" in caplog.text, caplog.text
    assert "192.168.1.10" in caplog.text, \
        "the warning must name the kept BIND_IP"


def test_sync_identical_ip_writes_nothing(user_home, monkeypatch):
    """Stored BIND_IP equals the interface's current IP: no write at
    all (no .bak churn, file untouched)."""
    (user_home / ".asoundrc").write_text(ASOUNDRC_STALE)
    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "192.168.1.10"})

    from inferno_gui.core.config import InfernoConfig, sync_bind_ip

    saves = []
    monkeypatch.setattr(
        InfernoConfig, "save",
        lambda self, backup=True: saves.append(backup))

    assert sync_bind_ip("eth0") is False
    assert saves == [], "identical IP must not rewrite the .asoundrc"
    assert (user_home / ".asoundrc").read_text() == ASOUNDRC_STALE


# ── call point (a): settings_tab.save_settings ────────────────────────


def test_save_settings_writes_current_interface_ip(
        user_home, monkeypatch, silenced_dialogs):
    """(a) Save Configuration re-derives BIND_IP from the selected
    interface: a stale stored IP is replaced by the NIC's current IP,
    all other keys intact — the production report's exact scenario."""
    st = _settings_tab(monkeypatch, user_home, ASOUNDRC_STALE,
                       ["eth0"], {"eth0": "10.0.0.9"})

    st.save_settings()

    content = (user_home / ".asoundrc").read_text()
    assert 'BIND_IP "10.0.0.9"' in content, content
    assert 'NAME "FieldCard"' in content, content
    assert 'SAMPLE_RATE "48000"' in content, content
    assert "TX_CHANNELS 16" in content, content
    assert "RX_CHANNELS 16" in content, content


def test_save_settings_without_interface_ip_keeps_bind_ip(
        user_home, monkeypatch, silenced_dialogs, caplog):
    """(b) No usable IP on the NIC: Save keeps the old BIND_IP and
    logs a warning instead of writing an empty bind address."""
    st = _settings_tab(monkeypatch, user_home, ASOUNDRC_STALE,
                       ["eth0"], {"eth0": None})

    with caplog.at_level(logging.WARNING, logger="inferno_gui.core.config"):
        st.save_settings()

    content = (user_home / ".asoundrc").read_text()
    assert 'BIND_IP "192.168.1.10"' in content, content
    assert "has no IP" in caplog.text, caplog.text


# ── call point (b): genuine user interface change ──────────────────────


def test_user_iface_change_syncs_bind_ip(user_home, monkeypatch):
    """(b) Changing the interface selection in the settings tab syncs
    BIND_IP immediately — the field user's "re-select the NIC" now
    actually fixes the stored value."""
    st = _settings_tab(monkeypatch, user_home, ASOUNDRC_STALE,
                       ["eth0", "eth1"],
                       {"eth0": "192.168.1.10", "eth1": "10.0.0.9"})

    st.iface_combo.setCurrentIndex(st.iface_combo.findData("eth1"))
    _app.processEvents()

    content = (user_home / ".asoundrc").read_text()
    assert 'BIND_IP "10.0.0.9"' in content, content


def test_construction_does_not_sync_bind_ip(user_home, monkeypatch):
    """Programmatic restores (startup load, refresh, control-tab push)
    do NOT rewrite the .asoundrc — only genuine user selections and
    the three approved call points sync. This pins the restore guard:
    an implementation without it would rewrite the file here (and
    write defaults before load_settings has populated the config)."""
    import inferno_gui.core.app_settings as app_settings
    settings = app_settings.user_settings("control")
    settings.setValue("selected_interface", "eth1")
    settings.sync()

    st = _settings_tab(monkeypatch, user_home, ASOUNDRC_STALE,
                       ["eth0", "eth1"],
                       {"eth0": "192.168.1.10", "eth1": "10.0.0.9"})

    assert st.iface_combo.currentData() == "eth1", "saved selection restored"
    assert (user_home / ".asoundrc").read_text() == ASOUNDRC_STALE, \
        "programmatic restore must not rewrite .asoundrc"


# ── call point (c): PTP start (control tab) ────────────────────────────


class _Signal:
    """Minimal stand-in for a Qt signal (only connect is needed)."""

    def connect(self, *args, **kwargs):
        pass


class FakeQProcess:
    """Stand-in for QProcess: no real processes, sudo check succeeds."""

    ProcessState = QProcess.ProcessState
    readyReadStandardOutput = _Signal()
    readyReadStandardError = _Signal()
    finished = _Signal()

    def start(self, *args, **kwargs):
        pass

    def waitForFinished(self, timeout=None):
        return True

    def exitCode(self):
        return 0

    def state(self):
        return QProcess.ProcessState.Running

    def terminate(self):
        pass

    def kill(self):
        pass


def test_ptp_start_syncs_bind_ip(user_home, monkeypatch, tmp_path, caplog):
    """(c) PTP start re-syncs BIND_IP from the selected interface
    before inferno begins running — covers a DHCP change while the GUI
    was closed. Silent by design: the change is logged, no popup."""
    (user_home / ".asoundrc").write_text(ASOUNDRC_STALE)
    _fake_interfaces(monkeypatch, ["eth-test"], {"eth-test": "10.0.0.9"})

    import inferno_gui.core.config as cfg_mod
    import inferno_gui.ui.control_tab as ct_mod
    from inferno_gui.ui.control_tab import ControlTab

    monkeypatch.setattr(ct_mod, "QProcess", FakeQProcess)
    monkeypatch.setattr(cfg_mod, "get_statime_binary", lambda: Path("/bin/sh"))
    config_tmp = tmp_path / "statime-v2.toml"
    monkeypatch.setattr(cfg_mod, "get_default_statime_config",
                        lambda v="v2": config_tmp)

    ct = ControlTab()
    _app.processEvents()
    monkeypatch.setattr(ct, "_create_pipewire_nodes", lambda: None)
    monkeypatch.setattr(ct, "_destroy_pipewire_nodes", lambda: None)

    with caplog.at_level(logging.INFO, logger="inferno_gui.core.config"):
        ct.start_ptp()

    content = (user_home / ".asoundrc").read_text()
    assert 'BIND_IP "10.0.0.9"' in content, content
    assert ("Updated BIND_IP in ~/.asoundrc: 192.168.1.10 -> 10.0.0.9"
            in caplog.text), caplog.text
