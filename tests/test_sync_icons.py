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

from PyQt6.QtCore import QSettings
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
    # beide Icons sind grün (identisch zum Cached-Icon)
    assert calls[0][1] == mw._icon_locked.cacheKey()
    mw.hide()


def test_no_icon_swap_when_state_unchanged(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    # erster Locked-Payload schaltet (real, vor dem Patchen) auf grün
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert mw._sync_icons_locked is True

    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    # identischer Locked-Payload zweimal: Merker verhindert Swap
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    mw._on_sync_status(dict(_LOCKED_PAYLOAD))
    assert calls == [], "identical locked payload must not swap icons"
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
