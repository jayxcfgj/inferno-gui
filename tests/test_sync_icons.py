# tests/test_sync_icons.py
"""Icon-Swap-Tests: Fenster- und Tray-Icon wechseln live zwischen
schwarz/weiß (nicht sync) und grün (Locked).

Locked exakt: ptp_state == 'SLAVE' and ptp_offset is not None
              and ptp_offset <= 200 - sonst schwarz/weiß.
Swap nur bei Zustandswechsel (Merker _sync_icons_locked, Start False).

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_sync_icons.py -v
"""
import os
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QObject, QProcess, QSettings, pyqtSignal
from PyQt6.QtWidgets import QApplication

# QSettings-Speicher auf ein Temp-Verzeichnis umleiten, damit die echten
# User-Settings (~/.config/InfernoGUI) von keinem Test angefasst werden.
_TEMPS = tempfile.mkdtemp(prefix="inferno-gui-test-settings-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)

# PyQt haelt keine Referenz auf die QApplication: wird der Python-Wrapper
# garbage-collected, zerstoert Qt die App samt aller Widgets. Deshalb die
# Referenz modulglobal halten (Muster tests/test_lock_gate_wiring.py).
_APP = None


def _get_app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture
def qt_offscreen():
    """QApplication bereitstellen (modulglobal gehalten)."""
    return _get_app()


_LOCKED_PAYLOAD = {
    'ptp_running': True,
    'ptp_state': 'SLAVE',
    'ptp_offset': 200,
    'ptp_freq': 0,
}


class _StubQProcess(QObject):
    """QProcess-Ersatz ohne echte Prozesse: terminate + waitForFinished
    emuliert das reale Ende-Verhalten (finished feuert synchron im
    waitForFinished, genau wie beim echten QProcess)."""

    ProcessState = QProcess.ProcessState
    readyReadStandardOutput = pyqtSignal()
    readyReadStandardError = pyqtSignal()
    finished = pyqtSignal(int, object)

    def __init__(self):
        super().__init__()
        self._terminated = False

    def start(self, *args, **kwargs):
        pass

    def terminate(self):
        self._terminated = True

    def kill(self):
        pass

    def exitCode(self):
        return 0

    def state(self):
        return QProcess.ProcessState.Running

    def waitForFinished(self, timeout=None):
        if self._terminated:
            self._terminated = False
            self.finished.emit(0, QProcess.ExitStatus.NormalExit)
        return True


def _make_control_tab(monkeypatch):
    """ControlTab mit Stub-QProcess bauen (keine echten Prozesse).

    Die QProcess-Klasse muss VOR dem ControlTab() gepatcht werden, weil
    init_ui bereits im Konstruktor ptp_process erzeugt (Muster
    tests/test_lock_gate_wiring.py).
    """
    import inferno_gui.ui.control_tab as ct_mod
    from inferno_gui.ui.control_tab import ControlTab

    monkeypatch.setattr(ct_mod, "QProcess", _StubQProcess)
    return ControlTab()


def test_icon_swaps_on_locked_status(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    # Start: schwarz/weiß
    assert mw._sync_icons_locked is False
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_locked is True
    assert len(calls) == 2 and {c[0] for c in calls} == {"window", "tray"}
    # beide Icons sind grün (identisch zum Cached-Icon), ohne Reihenfolge-Annahme
    assert {c[1] for c in calls} == {mw._icon_locked.cacheKey()}
    mw.hide()


def test_no_icon_swap_when_state_unchanged(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    # erster Locked-Payload schaltet real auf grün (2 Calls)
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_locked is True
    assert len(calls) == 2
    # identischer Locked-Payload zweimal: Merker verhindert Swap
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert len(calls) == 2, "identical locked payload must not swap icons"
    mw.hide()


def test_icon_not_green_without_full_lock_condition(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))

    payloads = [
        {'ptp_running': True, 'ptp_state': 'SLAVE', 'ptp_offset': 201, 'ptp_freq': 0},
        {'ptp_running': True, 'ptp_state': 'MASTER', 'ptp_offset': None, 'ptp_freq': 0},
        {'ptp_running': True, 'ptp_state': 'FAULTY', 'ptp_offset': 50, 'ptp_freq': 0},
        {'ptp_running': False, 'ptp_state': None, 'ptp_offset': None, 'ptp_freq': None},
        {'ptp_running': True, 'ptp_state': 'SLAVE', 'ptp_offset': None, 'ptp_freq': 0},
    ]
    for payload in payloads:
        mw._on_sync_status(payload)
        assert mw._sync_icons_locked is False, f"must stay not-locked: {payload}"
    assert calls == [], "no lock condition must not swap icons"
    mw.hide()


def test_start_icon_is_black_and_white(qt_offscreen):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    assert mw._sync_icons_locked is False
    assert mw.tray_icon.icon().cacheKey() == mw._icon_not_sync.cacheKey(), \
        "initial tray icon must be the black/white icon.png"
    mw.hide()


def test_icon_swaps_via_real_signal(qt_offscreen, monkeypatch):
    """End-to-End über das echte Signal-Wiring: das connect-Statement in
    MainWindow._connect_signals und die Payload-Keys von ControlTab._emit_status
    müssen zusammenpassen - direkte _on_sync_status-Aufrufe decken das nicht ab."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    # Echtes Signal mit den _emit_status-Payload-Keys feuern
    mw.control_tab.status_changed.emit(
        {'ptp_running': True, 'ptp_state': 'SLAVE', 'ptp_offset': 120, 'ptp_freq': 0})
    assert mw._sync_icons_locked is True
    assert len(calls) == 2 and {c[0] for c in calls} == {"window", "tray"}
    mw.hide()


def test_icon_swaps_back_when_lock_lost(qt_offscreen, monkeypatch):
    """Grün -> schwarz/weiß: nach verlorenem Lock (z.B. MASTER ohne Offset)
    müssen beide Icons wieder schwarz/weiß sein (echtes Signal)."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    # erst Locked -> grün
    mw.control_tab.status_changed.emit(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_locked is True
    assert len(calls) == 2
    # dann Lock verloren -> schwarz/weiß
    mw.control_tab.status_changed.emit(
        {'ptp_running': True, 'ptp_state': 'MASTER', 'ptp_offset': None, 'ptp_freq': 0})
    assert mw._sync_icons_locked is False
    assert len(calls) == 4
    assert {c[1] for c in calls[2:]} == {mw._icon_not_sync.cacheKey()}, \
        "both icons must be the black/white icon after lock loss"
    mw.hide()


def test_status_changed_emitted_when_ptp_process_dies(qt_offscreen, monkeypatch):
    """Stirbt der PTP-Prozess von selbst, muss status_changed feuern - sonst
    läuft der MainWindow-Icon-Handler nie und das Icon bleibt grün."""
    ct = _make_control_tab(monkeypatch)
    emissions = []
    ct.status_changed.connect(lambda s: emissions.append(dict(s)))
    # Locked-Zustand simulieren, dann stirbt der Prozess von selbst
    ct.is_ptp_running = True
    ct._ptp_state = 'SLAVE'
    ct._ptp_offset = 100
    ct._ptp_finished(1, QProcess.ExitStatus.CrashExit)
    assert emissions == [{
        'ptp_running': False,
        'ptp_state': '',
        'ptp_offset': None,
        'ptp_freq': None,
    }], "process death must emit the reset status so the icon can unlock"


def test_stop_ptp_emits_status_exactly_once(qt_offscreen, monkeypatch):
    """User-Stop: _ptp_finished liefert beim process-finished bereits das
    status_changed-Emit - stop_ptp darf nicht zusätzlich emittieren
    (doppelter Emit ist via Merker zwar harmlos, aber unsauber)."""
    ct = _make_control_tab(monkeypatch)
    monkeypatch.setattr(ct, "_destroy_pipewire_nodes", lambda: None)
    emissions = []
    ct.status_changed.connect(lambda s: emissions.append(dict(s)))
    ct.is_ptp_running = True
    ct._ptp_state = 'SLAVE'
    ct._ptp_offset = 100
    ct.stop_ptp()
    assert len(emissions) == 1, \
        f"exactly one status emission on user stop, got {len(emissions)}"
    assert emissions[0]['ptp_running'] is False
