# tests/test_sync_icons.py
"""Icon-Swap-Tests: Fenster- und Tray-Icon folgen der Ampel-Logik aus
sync_state.tray_state (Single Source of Truth):

grün    -> icon.svg          (SLAVE, |offset| <= 200)
gelb    -> icon_syncing.svg  (SLAVE, 200 < |offset| <= 1000)
schwarz -> icon.png          (alles andere: FAULTY, gestoppt, > 1000,
                              MASTER, LISTENING/PASSIVE, UNCALIBRATED,
                              kein Offset, None)

Swap nur bei Zustandswechsel (Merker _sync_icons_state, Start 'black').

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_sync_icons.py -v
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QObject, QProcess, QSettings, pyqtSignal
from PyQt6.QtGui import QIcon
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


def _payload(state, offset):
    return {'ptp_running': True, 'ptp_state': state, 'ptp_offset': offset,
            'ptp_freq': 0}


def _watch_icons(mw, monkeypatch):
    """setWindowIcon + tray.setIcon nach cacheKey mitschneiden."""
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    return calls


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


def test_syncing_svg_asset_exists_and_loads(qt_offscreen):
    """Asset-Test: icon_syncing.svg existiert und laedt als nicht-leeres QIcon."""
    import inferno_gui.ui.main_window as mw_mod

    svg = Path(mw_mod.__file__).parent.parent / 'assets' / 'icon_syncing.svg'
    assert svg.exists(), "icon_syncing.svg must exist next to icon.svg"
    icon = QIcon(str(svg))
    assert not icon.isNull(), "icon_syncing.svg must load as a valid QIcon"


def test_icon_swaps_on_locked_status(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    # Start: schwarz/weiß
    assert mw._sync_icons_state == 'black'
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_state == 'green'
    assert len(calls) == 2 and {c[0] for c in calls} == {"window", "tray"}
    # beide Icons sind grün (identisch zum Cached-Icon), ohne Reihenfolge-Annahme
    assert {c[1] for c in calls} == {mw._icon_locked.cacheKey()}
    mw.hide()


def test_syncing_status_uses_yellow_icon(qt_offscreen, monkeypatch):
    """SLAVE mit Offset 500 (201..1000) => gelbes Syncing-Icon an
    Fenster UND Tray, Zustands-Merker 'yellow'."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    mw._on_sync_status(_payload('SLAVE', 500))
    assert mw._sync_icons_state == 'yellow'
    assert len(calls) == 2 and {c[0] for c in calls} == {"window", "tray"}
    assert {c[1] for c in calls} == {mw._icon_syncing.cacheKey()}
    mw.hide()


def test_yellow_boundaries(qt_offscreen, monkeypatch):
    """Grenzen der gelben Zone: 201 ns => gelb, 1001 ns => schwarz."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    mw._on_sync_status(_payload('SLAVE', 201))
    assert mw._sync_icons_state == 'yellow'
    assert {c[1] for c in calls} == {mw._icon_syncing.cacheKey()}
    mw._on_sync_status(_payload('SLAVE', 1001))
    assert mw._sync_icons_state == 'black'
    assert {c[1] for c in calls[2:]} == {mw._icon_not_sync.cacheKey()}
    mw.hide()


def test_no_icon_swap_when_state_unchanged(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    # erster Locked-Payload schaltet real auf grün (2 Calls)
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_state == 'green'
    assert len(calls) == 2
    # identischer Locked-Payload zweimal: Merker verhindert Swap
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert len(calls) == 2, "identical locked payload must not swap icons"
    mw.hide()


def test_icon_not_green_without_full_lock_condition(qt_offscreen, monkeypatch):
    """Nicht-grün-und-nicht-gelb-Zustände: FAULTY, MASTER, gestoppt,
    SLAVE ohne Offset => schwarz, kein Icon-Swap."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)

    payloads = [
        _payload('MASTER', None),
        _payload('FAULTY', 50),
        {'ptp_running': False, 'ptp_state': None, 'ptp_offset': None,
         'ptp_freq': None},
        _payload('SLAVE', None),
    ]
    for payload in payloads:
        mw._on_sync_status(payload)
        assert mw._sync_icons_state == 'black', f"must stay black: {payload}"
    assert calls == [], "no lock/sync condition must not swap icons"
    mw.hide()


def test_icon_yellow_for_large_negative_offset(qt_offscreen, monkeypatch):
    """SLAVE mit -500 ns: |offset| = 500 <= 1000 => gelb (nicht schwarz,
    nicht grün)."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    mw._on_sync_status(_payload('SLAVE', -500))
    assert mw._sync_icons_state == 'yellow'
    assert {c[1] for c in calls} == {mw._icon_syncing.cacheKey()}
    mw.hide()


def test_icon_green_for_small_negative_offset(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    mw._on_sync_status(_payload('SLAVE', -150))
    assert mw._sync_icons_state == 'green'      # abs(-150) <= 200
    assert len(calls) == 2
    mw.hide()


def test_start_icon_is_black_and_white(qt_offscreen):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    assert mw._sync_icons_state == 'black'
    assert mw.tray_icon.icon().cacheKey() == mw._icon_not_sync.cacheKey(), \
        "initial tray icon must be the black/white icon.png"
    mw.hide()


def test_icon_swaps_via_real_signal(qt_offscreen, monkeypatch):
    """End-to-End über das echte Signal-Wiring: das connect-Statement in
    MainWindow._connect_signals und die Payload-Keys von ControlTab._emit_status
    müssen zusammenpassen - direkte _on_sync_status-Aufrufe decken das nicht ab."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    # Echtes Signal mit den _emit_status-Payload-Keys feuern
    mw.control_tab.status_changed.emit(
        {'ptp_running': True, 'ptp_state': 'SLAVE', 'ptp_offset': 120, 'ptp_freq': 0})
    assert mw._sync_icons_state == 'green'
    assert len(calls) == 2 and {c[0] for c in calls} == {"window", "tray"}
    mw.hide()


def test_icon_swaps_back_when_lock_lost(qt_offscreen, monkeypatch):
    """Grün -> schwarz/weiß: nach verlorenem Lock (z.B. MASTER ohne Offset)
    müssen beide Icons wieder schwarz/weiß sein (echtes Signal)."""
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = _watch_icons(mw, monkeypatch)
    # erst Locked -> grün
    mw.control_tab.status_changed.emit(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_state == 'green'
    assert len(calls) == 2
    # dann Lock verloren -> schwarz/weiß
    mw.control_tab.status_changed.emit(_payload('MASTER', None))
    assert mw._sync_icons_state == 'black'
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
