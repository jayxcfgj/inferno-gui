"""Offscreen-Layout-Smoke-Test für ControlTab (kein pytest nötig).

Run: QT_QPA_PLATFORM=offscreen python3 tests/test_layout_smoke.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QHBoxLayout


def test_layout():
    app = QApplication.instance() or QApplication(sys.argv)
    from inferno_gui.ui.control_tab import ControlTab

    ct = ControlTab()
    ct.resize(1000, 750)
    ct.show()
    app.processEvents()

    # 1) Beide Boxen hängen in EINEM horizontalen Layout (verschachtelt:
    #    scroll- QVBoxLayout → top_row QHBoxLayout → Gruppen)
    outer = ct.ptp_group.parentWidget().layout()
    top = None
    for i in range(outer.count()):
        item = outer.itemAt(i)
        if item.layout() is not None and item.layout().indexOf(ct.ptp_group) != -1:
            top = item.layout()
            break
    assert top is not None, "PTP box not inside a nested row layout"
    assert isinstance(top, QHBoxLayout), "row layout is not horizontal"
    assert top.indexOf(ct.inferno_group) != -1, "Inferno box not in same row"

    app.processEvents()
    assert abs(ct.ptp_group.width() - ct.inferno_group.width()) <= 6, \
        f"boxes not 50/50: {ct.ptp_group.width()} vs {ct.inferno_group.width()}"

    pl = ct.ptp_layout
    # 2) Genau 4 Zeilen, keine lose Widgets
    assert pl.count() == 4, f"PTP box must have exactly 4 rows, has {pl.count()}"
    rows = []
    for i in range(pl.count()):
        item = pl.itemAt(i)
        assert item.layout() is not None, f"row {i} is a loose widget, expected a row layout"
        rows.append(item.layout())

    # Zeile 0: Interface-Auswahl OHNE Radios; Zeile 1: Radios
    for w in (ct.interface_combo, ct.refresh_iface_btn):
        assert rows[0].indexOf(w) != -1, f"{w} not in PTP row 0"
    assert rows[0].indexOf(ct.ptp_v1_radio) == -1, "radios must be moved out of row 0"
    for w in (ct.ptp_v1_radio, ct.ptp_v2_radio):
        assert rows[1].indexOf(w) != -1, f"{w} not in PTP row 1 (radio row)"

    # 3) Keine Zeile läuft über die Boxbreite hinaus (kein Clipping).
    #    contentsRect() der Box liefert exakt die verfügbare Inhaltsbreite (462px bei 1000px Fenster).
    available = pl.contentsRect().width()
    for i, row in enumerate(rows):
        need = row.totalMinimumSize().width()
        assert need <= available, \
            f"PTP row {i} needs {need}px but only {available}px available"

    # 4) Radios gekürzt, IEEE nur noch im Tooltip
    assert ct.ptp_v1_radio.text() == "PTPv1"
    assert ct.ptp_v2_radio.text() == "PTPv2"
    assert "IEEE 1588-2002" in ct.ptp_v1_radio.toolTip()
    assert "IEEE 1588-2008" in ct.ptp_v2_radio.toolTip()

    # 5) Zeile 2 = Start/Stop/Sync, Zeile 3 = IP+State+Offset+Freq-Statusleiste
    for w in (ct.start_ptp_btn, ct.stop_ptp_btn, ct.sync_light, ct.sync_label):
        assert rows[2].indexOf(w) != -1, f"{w} not in PTP row 2"
    for w in (ct.ip_label, ct.ptp_state_label, ct.ptp_offset_label, ct.ptp_freq_label):
        assert rows[3].indexOf(w) != -1, f"{w} not in status strip (row 3)"

    # 6) Inferno-Notiz passt bei halber Breite auf max. 2 Zeilen
    line = ct.inferno_note.fontMetrics().lineSpacing()
    assert ct.inferno_note.height() <= 2 * line + 6, \
        f"note wraps beyond 2 lines: {ct.inferno_note.height()}px vs 2x{line}px"

    # 7) Am kleinstmöglichen Fenster darf keine Zeile abschneiden
    ct.resize(ct.minimumSizeHint().width(), 750)
    app.processEvents()
    app.processEvents()
    available = pl.contentsRect().width()
    assert available > 0, "layout not activated at minimum width"
    for i, row in enumerate(rows):
        need = row.totalMinimumSize().width()
        assert need <= available, \
            f"PTP row {i} clips at min width: needs {need}px, only {available}px available"

    # Notiz: am Maximum 2 Zeilen (bestehende Assertion bei 1000px bleibt),
    # am Minimum reichen 3 Zeilen
    line = ct.inferno_note.fontMetrics().lineSpacing()
    assert ct.inferno_note.height() <= 3 * line + 6, \
        f"note wraps beyond 3 lines at min width: {ct.inferno_note.height()}px"

    print("PASS: layout smoke test")


if __name__ == "__main__":
    test_layout()
