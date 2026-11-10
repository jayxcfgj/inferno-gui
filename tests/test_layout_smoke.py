"""Offscreen-Layout-Smoke-Test für ControlTab (kein pytest nötig).

Run: QT_QPA_PLATFORM=offscreen python3 tests/test_layout_smoke.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout

# QSettings-Speicher auf ein Temp-Verzeichnis umleiten, damit die echten
# User-Settings (~/.config/InfernoGUI) von keinem Test angefasst werden
# (schützt auch test_layout: ControlTab schreibt ptp_version bei Initialisierung).
_TEMPS = tempfile.mkdtemp(prefix="inferno-gui-test-settings-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)


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

    # 6) Inferno-Statuszeile entfernt (war statisch – wird nie aktualisiert)
    assert not hasattr(ct, "inferno_status_label"), "static Inferno status line must be gone"

    # 7) Ansatz A: Zeilen füllen die Boxbreite aus (bei 1000px)
    # Zeile 0: Combo wächst über ihr 200px-Minimum hinaus (kein Loch vor ↻)
    _gap = ct.refresh_iface_btn.x() - (ct.interface_combo.x() + ct.interface_combo.width())
    assert _gap <= 8, \
        f"combo does not reach the refresh button (hole on the right): {_gap}px gap"
    # Stretch-Faktor 1: die gesamte Zusatzbreite geht an die Combo, nicht an das Label
    _lbl = rows[0].itemAt(0).widget()
    assert _lbl.width() <= _lbl.sizeHint().width() + 2, \
        f"combo does not absorb the extra width (stretch factor missing): label {_lbl.width()}px vs natural {_lbl.sizeHint().width()}px"
    # Zeile 1: Radios als Paar zentriert (Spacer links und rechts)
    assert rows[1].itemAt(0).spacerItem() is not None, "radio row missing left spacer (not centered)"
    assert rows[1].itemAt(rows[1].count() - 1).spacerItem() is not None, \
        "radio row missing right spacer (not centered)"
    # Symmetrie: beide Spacer gleich groß (Paar wirklich mittig)
    _sl = rows[1].itemAt(0).geometry().width()
    _sr = rows[1].itemAt(rows[1].count() - 1).geometry().width()
    assert abs(_sl - _sr) <= 1, f"radio spacers asymmetric: {_sl}px vs {_sr}px"
    # Zeile 3: 3 Spacer zwischen den 4 Labels, freq letztes Item → reicht bis zur Kante
    assert rows[3].count() >= 7, f"status strip not distributed: {rows[3].count()} items"
    assert rows[3].indexOf(ct.ptp_freq_label) == rows[3].count() - 1, \
        "freq label not last (trailing hole on the right)"
    # AlignTop: PTP-Box kürzer als Inferno-Box (nicht auf deren Höhe gezogen)
    assert ct.ptp_group.height() < ct.inferno_group.height(), \
        f"PTP box stretched to Inferno height: {ct.ptp_group.height()} vs {ct.inferno_group.height()}"

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
        # +1: Rundungstoleranz; Margin ist 0px by design (rows determine the minimum)
        assert need <= available + 1, \
            f"PTP row {i} clips at min width: needs {need}px, only {available}px available"

    # Notiz: am Maximum 2 Zeilen (bestehende Assertion bei 1000px bleibt),
    # am Minimum reichen 3 Zeilen
    line = ct.inferno_note.fontMetrics().lineSpacing()
    assert ct.inferno_note.height() <= 3 * line + 6, \
        f"note wraps beyond 3 lines at min width: {ct.inferno_note.height()}px"

    print("PASS: layout smoke test")


def test_main_window_clamp():
    """MainWindow öffnet an der Qt-Mindestbreite (Clamp); Höhe bleibt erhalten.

    Deckt den Clamp aus MainWindow.__init__ (nach _load_window_state) ab:
    (a) frischer Start ohne gespeicherte Geometrie → width == minimumSizeHint().width()
    (b) gespeicherte Geometrie 1400x900 → Höhe 900 bleibt, Breite wird geclampt
    (c) maximiert gespeicherte Geometrie → Clamp wird übersprungen
    (d) an der Mindestbreite läuft keine PTP-Zeile über die Box hinaus

    QSettings-Speicher werden per setPath umgeleitet (siehe Modulkopf), die
    echten User-Settings (~/.config/InfernoGUI) bleiben unberührt.
    """
    from inferno_gui.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)

    # defensively wiederholen: Umleitung gilt für diesen Prozess (idempotent)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)
    settings = QSettings("InfernoGUI", "window")
    settings.clear()  # leerer Start: keine gespeicherte Geometrie

    def capture_geometry(size=None, maximized=False):
        """Seed-Geometrie cappen: MainWindow bauen, Zustand setzen, saveGeometry()."""
        seed_win = MainWindow()
        seed_win.show()
        app.processEvents()
        if maximized:
            seed_win.setWindowState(Qt.WindowState.WindowMaximized)
        elif size:
            seed_win.resize(*size)
        app.processEvents()
        app.processEvents()
        geo = seed_win.saveGeometry()
        seed_win.hide()  # close() öffnet den Tray-QMessageBox-Modal (hängt offscreen)
        seed_win.deleteLater()
        return geo

    # (a) Frischer Start: Clamp greift
    mw = MainWindow()
    mw.show()
    for _ in range(6):
        app.processEvents()  # ShowEvent refresht Interfaces → Layout erneut aktivieren
    min_w = mw.minimumSizeHint().width()
    assert mw.width() == min_w, \
        f"fresh start: width {mw.width()} != minimum {min_w}"

    # (d) An der Clamped-Breite bleibt jede PTP-Zeile innerhalb der Box
    pl = mw.control_tab.ptp_layout
    available = pl.contentsRect().width()
    assert available > 0, "layout not activated at clamped width"
    for i in range(pl.count()):
        row = pl.itemAt(i).layout()
        assert row is not None, f"PTP row {i} is not a row layout"
        need = row.totalMinimumSize().width()
        # +1: Rundungstoleranz; Margin ist 0px by design (rows determine the minimum)
        assert need <= available + 1, \
            f"PTP row {i} clips at clamped width: needs {need}px, only {available}px"
    mw.hide()  # close() öffnet den Tray-QMessageBox-Modal (hängt offscreen)
    mw.deleteLater()

    # (b) Gespeicherte Geometrie 1400x900: Höhe bleibt, Breite wird geclampt
    settings.setValue("geometry", capture_geometry(size=(1400, 900)))
    settings.sync()
    mw_h = MainWindow()
    mw_h.show()
    for _ in range(6):
        app.processEvents()
    min_w = mw_h.minimumSizeHint().width()
    assert mw_h.height() == 900, \
        f"saved height lost: {mw_h.height()} != 900"
    assert mw_h.width() == min_w, \
        f"clamp not applied on saved geometry: width {mw_h.width()} != {min_w}"
    mw_h.hide()  # close() öffnet den Tray-QMessageBox-Modal (hängt offscreen)
    mw_h.deleteLater()

    # (c) Maximierte Geometrie: Clamp wird übersprungen
    settings.setValue("geometry", capture_geometry(maximized=True))
    settings.sync()
    mw_max = MainWindow()
    mw_max.show()
    for _ in range(6):
        app.processEvents()
    assert mw_max.isMaximized(), "maximized seed not restored as maximized"
    assert mw_max.width() != mw_max.minimumSizeHint().width(), \
        "clamp ran on a maximized window (should be skipped)"
    mw_max.hide()  # close() öffnet den Tray-QMessageBox-Modal (hängt offscreen)
    mw_max.deleteLater()

    # Temp-Settings-Verzeichnis bleibt in /tmp zurück (Prozess-global umgeleitet)

    print("PASS: main window clamp test")


if __name__ == "__main__":
    test_layout()
    test_main_window_clamp()
