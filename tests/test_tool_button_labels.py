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


# How-to tooltip for the qpwgraph launch button (exact wording per spec).
QPWGRAPH_TOOLTIP = (
    "Route audio inside PipeWire: drag ports to connect Inferno nodes with your apps. "
    "To keep routes across restarts: Patchbay > Save As... then Activated re-applies them "
    "automatically, Exclusive drops everything not in the patchbay, Edit changes the saved connections."
)


def test_qpwgraph_button_tooltip():
    """The qpwgraph button explains the patchbay workflow (how to route
    and how to make routes survive restarts)."""
    app = QApplication.instance() or QApplication(sys.argv)
    from inferno_gui.ui.control_tab import ControlTab
    ct = ControlTab()
    app.processEvents()
    assert ct.qpwgraph_btn.toolTip() == QPWGRAPH_TOOLTIP, \
        f"qpwgraph tooltip changed:\n{ct.qpwgraph_btn.toolTip()!r}"


def test_save_reset_icons():
    """Settings save/reset buttons carry bundled SVG icons and emoji-free labels."""
    app = QApplication.instance() or QApplication(sys.argv)
    from PyQt6.QtCore import QSize
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    app.processEvents()

    for btn, label in ((st.save_btn, "Save Configuration"),
                       (st.reset_btn, "Reset to Defaults")):
        assert not btn.icon().isNull(), f"{label}: icon is null (missing asset?)"
        assert btn.iconSize().width() == 16 and btn.iconSize().height() == 16, \
            f"{label}: unexpected iconSize {btn.iconSize()}"
        assert btn.text() == label, f"save/reset label: {btn.text()!r} != {label!r}"
        assert "\U0001f4be" not in btn.text() and "\U0001f504" not in btn.text(), \
            "emoji glyph still in label"

    # Dirty marker: trailing '*' appended to the save label, icon preserved
    st._mark_dirty()
    assert st.save_btn.text() == "Save Configuration*", \
        f"dirty label: {st.save_btn.text()!r} != 'Save Configuration*'"
    assert not st.save_btn.icon().isNull(), "icon lost after _mark_dirty"
    assert not st.reset_btn.icon().isNull()
    assert st.reset_btn.text() == "Reset to Defaults"


def test_note_moved_to_test_button_tooltip():
    app = QApplication.instance() or QApplication(sys.argv)
    from inferno_gui.ui.control_tab import ControlTab
    ct = ControlTab()
    app.processEvents()
    # Note-Widget ist raus
    assert not hasattr(ct, "inferno_note"), "inferno_note still present"
    # Text steckt als lesbbarer (mindestens zweizeiliger) Tooltip am Button
    tip = ct.test_alsa_btn.toolTip()
    assert "activates automatically" in tip, f"tooltip missing note text: {tip!r}"
    assert "\n" in tip, "tooltip is one long line, unreadable"
