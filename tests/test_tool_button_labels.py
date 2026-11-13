# tests/test_tool_button_labels.py
"""Label-Regression: Tool-Buttons tragen das Funktions-Präfix, Symbole
und Gleichbreite bleiben erhalten, die Tab-Mindestbreite (ControlTab.
minimumSizeHint) wächst nicht.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_tool_button_labels.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

EXPECTED = {
    "netaudio_btn": "🌐 Dante Routing - Open NetAudio Web UI",
    "qpwgraph_btn": "PipeWire Routing - Open qpwgraph",
    "cable_btn": "PipeWire Settings - Open Cable",
}


def test_tool_button_labels():
    app = QApplication.instance() or QApplication(sys.argv)
    from inferno_gui.ui.control_tab import ControlTab
    ct = ControlTab()
    app.processEvents()
    for name, text in EXPECTED.items():
        assert getattr(ct, name).text() == text, \
            f"{name}: {getattr(ct, name).text()!r} != {text!r}"


def test_tool_buttons_equal_width_and_window_unchanged():
    app = QApplication.instance() or QApplication(sys.argv)
    from inferno_gui.ui.control_tab import ControlTab
    ct = ControlTab()
    ct.show()  # Layout muss aktiv sein, sonst melden alle Buttons width()==640
    app.processEvents()
    widths = {n: getattr(ct, n).width() for n in EXPECTED}
    assert len(set(widths.values())) == 1, f"buttons not equal width: {widths}"
    # Tab-Mindestbreite (ControlTab.minimumSizeHint, Basis fuer MainWindow-Resize)
    # darf durch die laengeren Texte nicht waechser werden
    assert ct.minimumSizeHint().width() == 760, \
        f"tab min width grew: {ct.minimumSizeHint().width()}px != 760px"
