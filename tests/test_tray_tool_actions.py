# tests/test_tray_tool_actions.py
"""Tray-Kontextmenue: alle drei Tools ansprechbar, Labels identisch zur GUI.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_tray_tool_actions.py -q
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

_TEMPS = tempfile.mkdtemp(prefix="inferno-tray-test-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)

EXPECTED = {
    "tray_netaudio_action": "🌐 Dante Routing - Open NetAudio Web UI",
    "tray_qpwgraph_action": "PipeWire Routing - Open qpwgraph",
    "tray_cable_action": "PipeWire Settings - Open Cable",
}


def test_tray_tool_actions_exist_with_gui_labels():
    app = QApplication.instance() or QApplication(sys.argv)
    from inferno_gui.ui.main_window import MainWindow
    win = MainWindow()
    app.processEvents()
    for name, text in EXPECTED.items():
        action = getattr(win, name, None)
        assert action is not None, f"{name} missing"
        assert action.text() == text, f"{name}: {action.text()!r} != {text!r}"
        assert action.receivers(action.triggered) >= 1, f"{name} not connected"
    win.hide()
    win.deleteLater()
