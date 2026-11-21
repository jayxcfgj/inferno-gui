# tests/test_control_tab_discovery.py
"""Control-tab wiring of the mDNS discovery kick.

PTP start must arm the tab's DiscoveryKicker with the CURRENTLY selected
interface's IP (so the probes leave via the Dante NIC); PTP stop - user
stop OR process death - must disarm it. The "Trigger discovery" button
sends exactly ONE probe immediately through the tab's injectable socket
factory (_probe_socket_factory).

Run: QT_QPA_PLATFORM=offscreen uv run --no-project --with pytest \
    --with PyQt6 --with tomli --with tomli-w \
    python -m pytest tests/test_control_tab_discovery.py -q
"""
import os
import socket
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QProcess, QSettings

# QSettings-Speicher auf ein Temp-Verzeichnis umleiten, damit die echten
# User-Settings (~/.config/InfernoGUI) von keinem Test angefasst werden
# (siehe test_lock_gate_wiring.py fuer das Muster).
_TEMPS = tempfile.mkdtemp(prefix="inferno-gui-test-settings-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)


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


class FakeSocket:
    """Records setsockopt/sendto/close; no real I/O ever happens."""

    def __init__(self, family, sock_type):
        assert family == socket.AF_INET, "probe must use IPv4"
        assert sock_type == socket.SOCK_DGRAM, "probe must use UDP"
        self.setsockopt_calls = []
        self.sent = []
        self.closed = False

    def setsockopt(self, level, optname, value):
        self.setsockopt_calls.append((level, optname, value))

    def sendto(self, data, addr):
        self.sent.append((bytes(data), addr))

    def close(self):
        self.closed = True


class FakeSocketFactory:
    """Injectable socket factory: hands out FakeSockets."""

    def __init__(self):
        self.sockets = []

    def __call__(self, family, sock_type):
        sock = FakeSocket(family, sock_type)
        self.sockets.append(sock)
        return sock


_APP = None


def _get_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _make_tab(monkeypatch):
    """ControlTab with mocked externals and a known selected interface.

    - QProcess (inferno_gui.ui.control_tab) -> FakeQProcess
    - get_statime_binary -> existing path (/bin/sh)
    - get_default_statime_config -> temp file (not created, load() -> False)
    - _create/_destroy_pipewire_nodes -> no-ops (no real pw-cli calls)
    - combo selection: "eth-test" with a deterministic IP
    """
    _get_app()

    import inferno_gui.core.config as cfg_mod
    import inferno_gui.ui.control_tab as ct_mod
    from inferno_gui.ui.control_tab import ControlTab

    monkeypatch.setattr(ct_mod, "QProcess", FakeQProcess)
    monkeypatch.setattr(cfg_mod, "get_statime_binary", lambda: Path("/bin/sh"))
    config_tmp = Path(tempfile.mkdtemp(prefix="inferno-test-cfg-")) / "statime-v2.toml"
    monkeypatch.setattr(cfg_mod, "get_default_statime_config",
                        lambda v="v2": config_tmp)

    ct = ControlTab()
    _get_app().processEvents()

    # Deterministic interface selection with a known IP.
    ct.interface_combo.addItem("eth-test", "eth-test")
    ct._interface_ips["eth-test"] = "192.168.7.42"
    ct.interface_combo.setCurrentIndex(ct.interface_combo.findData("eth-test"))

    monkeypatch.setattr(ct, "_create_pipewire_nodes", lambda: None)
    monkeypatch.setattr(ct, "_destroy_pipewire_nodes", lambda: None)
    return ct


EXPECTED_INTERVALS_MS = [d * 1000 for d in (1, 6, 15, 35, 65)]


def _simulate_running_ptp(ct):
    """start_ptp + successful startup verification (emits ptp_started)."""
    ct.start_ptp()
    ct._verify_ptp_startup()
    assert ct.is_ptp_running is True


def test_ptp_start_arms_discovery_kicks_with_current_interface_ip(monkeypatch):
    ct = _make_tab(monkeypatch)
    assert ct.discovery_kicker.timers == [], "no probes before PTP start"
    _simulate_running_ptp(ct)
    timers = ct.discovery_kicker.timers
    assert [t.interval() for t in timers] == EXPECTED_INTERVALS_MS
    assert all(t.isSingleShot() for t in timers)
    assert ct.discovery_kicker.interface_ip == "192.168.7.42", \
        "probes must leave via the selected Dante NIC"


def test_ptp_start_failure_arms_no_probes(monkeypatch):
    """Startup verification fails (process died) -> ptp_started never
    emitted -> no probes scheduled."""
    ct = _make_tab(monkeypatch)
    ct.start_ptp()
    ct.ptp_process.state = \
        lambda: QProcess.ProcessState.NotRunning
    ct._verify_ptp_startup()
    assert ct.is_ptp_running is False
    assert ct.discovery_kicker.timers == []


def test_ptp_stop_disarms_discovery_kicks(monkeypatch):
    ct = _make_tab(monkeypatch)
    _simulate_running_ptp(ct)
    assert ct.discovery_kicker.timers, "kicks must be armed before stop"
    ct.stop_ptp()
    assert ct.discovery_kicker.timers == [], \
        "user stop must clear the scheduled probes"


def test_ptp_process_death_disarms_discovery_kicks(monkeypatch):
    ct = _make_tab(monkeypatch)
    _simulate_running_ptp(ct)
    ct._ptp_finished(0, QProcess.ExitStatus.NormalExit)
    assert ct.discovery_kicker.timers == [], \
        "process death must clear the scheduled probes"


def test_discovery_button_sends_exactly_one_probe(monkeypatch):
    ct = _make_tab(monkeypatch)
    factory = FakeSocketFactory()
    ct._probe_socket_factory = factory
    ct.discovery_btn.click()
    assert len(factory.sockets) == 1, "the button must send exactly ONE probe"
    sock = factory.sockets[0]
    assert len(sock.sent) == 1
    packet, addr = sock.sent[0]
    assert addr == ("224.0.0.251", 5353)
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
            socket.inet_aton("192.168.7.42")) in sock.setsockopt_calls
    assert sock.closed

    from inferno_gui.core.discovery_kick import build_mdns_ptr_query
    assert packet == build_mdns_ptr_query(), \
        "the button must send the real PTR query packet"


def test_discovery_button_label_and_tooltip(monkeypatch):
    ct = _make_tab(monkeypatch)
    assert ct.discovery_btn.text() == "Trigger discovery"
    assert ct.discovery_btn.toolTip() == (
        "Send an mDNS probe so the netaudio daemon re-discovers "
        "this device immediately"
    )
