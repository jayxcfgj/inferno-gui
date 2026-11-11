# tests/test_lock_gate_wiring.py
"""Wiring-Tests: PipeWire-Node-Erstellung wird durch stabilen PTP-Lock gegated.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_lock_gate_wiring.py -q
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QSettings, QProcess

# QSettings-Speicher auf ein Temp-Verzeichnis umleiten, damit die echten
# User-Settings (~/.config/InfernoGUI) von keinem Test angefasst werden.
_TEMPS = tempfile.mkdtemp(prefix="inferno-gui-test-settings-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)


class _Signal:
    """Minimal-Ersatz fuer ein Qt-Signal (nur connect wird benoetigt)."""

    def connect(self, *args, **kwargs):
        pass


class FakeQProcess:
    """Ersatz fuer QProcess: keine echten Prozesse, sudo-Check gelingt."""

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


# PyQt haelt keine Referenz auf die QApplication: wird der Python-Wrapper
# garbage-collected, zerstoert Qt die App samt aller Widgets ("wrapped C/C++
# object ... has been deleted"). Deshalb die Referenz modulglobal halten.
_APP = None


def _get_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _make_tab(monkeypatch):
    """ControlTab mit gemockten externen Abhaengigkeiten bauen.

    - QProcess (Modulinferno_gui.ui.control_tab) -> FakeQProcess
    - get_statime_binary -> existierender Pfad (/bin/sh)
    - get_default_statime_config -> Temp-Datei (nicht angelegt, load() -> False)
    - Interface-Combo mit einem echten Item bestücken
    - _create_pipewire_nodes/_destroy_pipewire_nodes -> Zähler/No-op
    """
    app = _get_app()

    import inferno_gui.ui.control_tab as ct_mod
    import inferno_gui.core.config as cfg_mod
    from inferno_gui.ui.control_tab import ControlTab

    monkeypatch.setattr(ct_mod, "QProcess", FakeQProcess)
    monkeypatch.setattr(cfg_mod, "get_statime_binary", lambda: Path("/bin/sh"))
    config_tmp = Path(tempfile.mkdtemp(prefix="inferno-test-config-")) / "statime-v2.toml"
    monkeypatch.setattr(cfg_mod, "get_default_statime_config", lambda v="v2": config_tmp)

    ct = ControlTab()
    app.processEvents()

    # Ein echtes Interface-Item (kein "No interfaces"-Pseudo-Eintrag)
    ct.interface_combo.addItem("eth0", "eth0")
    ct.interface_combo.setCurrentIndex(0)

    created = []
    monkeypatch.setattr(ct, "_create_pipewire_nodes", lambda: created.append(1))
    monkeypatch.setattr(ct, "_destroy_pipewire_nodes", lambda: None)
    return ct, created


def test_start_ptp_does_not_create_nodes_immediately(monkeypatch):
    ct, created = _make_tab(monkeypatch)
    ct.start_ptp()
    assert created == [], "nodes must not be created before lock"
    assert ct._awaiting_lock is True
    assert ct._lock_gate.threshold_ns == 1000   # v2 Standard
    assert ("Waiting for PTP lock before creating PipeWire nodes... "
            "(threshold 1000 ns)") in ct.terminal_output.toPlainText()


def test_v1_radio_uses_1500_ns(monkeypatch):
    ct, created = _make_tab(monkeypatch)
    ct.ptp_v1_radio.setChecked(True)
    ct.start_ptp()
    assert created == []
    assert ct._lock_gate.threshold_ns == 1500


def test_lock_triggers_single_node_creation(monkeypatch):
    from inferno_gui.core.lock_gate import LockGate

    ct, created = _make_tab(monkeypatch)
    ct.is_ptp_running = True
    ct._awaiting_lock = True
    ct._lock_gate = LockGate(1000, 5)
    monkeypatch.setattr(
        ct.parser, "get_sync_status",
        lambda: {'state': 'SLAVE', 'offset_ns': 500, 'freq_ppb': None},
    )
    for _ in range(5):
        ct._update_status_panel()
    assert len(created) == 1, "exactly one node creation on lock"
    assert ct._awaiting_lock is False
    for _ in range(5):
        ct._update_status_panel()
    assert len(created) == 1, "gate must be sticky - no repeated node creation"
    assert ("PTP locked (offset 500 ns, 5/5 ticks) - creating PipeWire nodes..."
            ) in ct.terminal_output.toPlainText()


def test_no_lock_keeps_waiting_and_logs(monkeypatch):
    from inferno_gui.core.lock_gate import LockGate

    ct, created = _make_tab(monkeypatch)
    ct.is_ptp_running = True
    ct._awaiting_lock = True
    ct._lock_gate = LockGate(1000, 5)
    monkeypatch.setattr(
        ct.parser, "get_sync_status",
        lambda: {'state': 'LISTENING', 'offset_ns': None, 'freq_ppb': None},
    )
    for _ in range(19):
        ct._update_status_panel()
    assert created == []
    assert ct._awaiting_lock is True
    assert "still waiting for lock" not in ct.terminal_output.toPlainText()
    ct._update_status_panel()  # 20. Tick = 10 s
    assert created == []
    assert ct._awaiting_lock is True
    assert ("still waiting for lock: state=LISTENING, offset=None ns"
            ) in ct.terminal_output.toPlainText()


def test_stop_during_wait_clears_flag(monkeypatch):
    ct, created = _make_tab(monkeypatch)
    ct.start_ptp()
    # Startup-Verifikation simulieren (der QTimer feuert im Test nicht)
    ct._verify_ptp_startup()
    assert ct.is_ptp_running is True
    ct.stop_ptp()
    assert ct._awaiting_lock is False
    assert created == []


def test_stop_during_starting_window_clears_gate_state(monkeypatch):
    """User-Stop waehrend des 2,5-s-Startfensters (_ptp_starting): Gate-State
    muss bedingungslos aufgeraeumt werden, damit _verify_ptp_startup danach
    keine Nodes mehr erzeugen kann."""
    ct, created = _make_tab(monkeypatch)
    ct.start_ptp()
    # Start-Fenster aktiv: _verify_ptp_startup wurde noch NICHT aufgerufen,
    # is_ptp_running ist daher noch False.
    assert ct._ptp_starting is True
    assert ct.is_ptp_running is False
    assert ct._awaiting_lock is True
    ct.stop_ptp()
    assert ct._awaiting_lock is False
    assert ct._lock_gate is None
    # Danach feuert _verify_ptp_startup doch noch - ohne Gate darf kein
    # Node-Aufruf mehr passieren, auch nicht bei stabilem Lock.
    ct._verify_ptp_startup()
    monkeypatch.setattr(
        ct.parser, "get_sync_status",
        lambda: {'state': 'SLAVE', 'offset_ns': 500, 'freq_ppb': None},
    )
    for _ in range(5):
        ct._update_status_panel()
    assert created == [], "no node creation after stop during starting window"


def test_ptp_exit_before_lock_clears_flag(monkeypatch):
    ct, created = _make_tab(monkeypatch)
    ct.start_ptp()
    assert ct._awaiting_lock is True
    ct._ptp_finished(1, QProcess.ExitStatus.CrashExit)
    assert ct._awaiting_lock is False
    assert created == []
    assert ("PTP exited before lock - no PipeWire nodes created"
            ) in ct.terminal_output.toPlainText()
