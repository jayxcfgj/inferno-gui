# PTP + Inferno nebeneinander (50/50) – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PTP- und Inferno-Box nebeneinander (exakt 50/50) anordnen und die PTP-Box auf 3 kompakte Zeilen verdichten, ohne die GUI-Breite zu ändern.

**Architecture:** In `ControlTab.init_ui()` werden die beiden bestehenden `QGroupBox`-Objekte statt untereinander in eine neue horizontale `QHBoxLayout` (`top_row`, je `stretch=1`) eingehängt. Die PTP-Box-Inhalte werden von 4 Zeilen (Interface-Zeile mit Versions-Label, IP-Label lose, Buttons-Zeile, Status-Grid) auf 3 Zeilen umgebaut (Interface+Radios, Start/Stop+Sync, Statusleiste). Alle bestehenden Widgets bleiben dieselben Objekte – Slots, Signale und Logik bleiben unangetastet.

**Tech Stack:** Python 3, PyQt6. Kein Test-Framework im Projekt (kein pytest installiert) → Offscreen-Smoke-Test als plain `python3`-Skript mit `QT_QPA_PLATFORM=offscreen`.

**Spec:** `docs/superpowers/specs/2026-11-10-ptp-inferno-side-by-side-design.md`

## Global Constraints

- GUI-Fensterbreite bleibt **1000px** (`main_window.py:30: setGeometry(200, 200, 1000, 750)`) – nicht ändern.
- Boxenbreite je **50/50** via `top_row.addWidget(group, 1)`.
- Verfügbare Inhaltsbreite pro Box gemessen: **462px** (Box-Außenbreite 492px).
- Gemessene Zeilen-Bedarfswerte (müssen ≤ 462px bleiben):
  - Zeile 1 (Interface+Combo200+↻+2 Radios, ohne Versions-Label): **~435px**
  - Zeile 2 (Start+Stop+Sync-Licht+Sync-Label 140): **~423px**
  - Zeile 3 (IP+State+Offset+Freq): **~328px**
- Radio-Texte exakt `PTPv1` / `PTPv2`, IEEE-Referenz **nur als Tooltip** (`IEEE 1588-2002` / `IEEE 1588-2008`). Radios werden nirgends über `.text()` ausgewertet (nur `isChecked()`/IDs – verifiziert).
- `Label "PTP Version:"` entfällt in Zeile 1 (passt sonst nicht: 477px > 462px).
- Combo-Mindestbreite bleibt **200px** (Reduktion auf 150px laut Spec ist bei entfallenem Label nicht nötig).
- Nur `control_tab.py` ändern – Settings-Tab, Logik, Icons, `_test_alsa_device`, Buttons-Gruppen bleiben unverändert.
- Nach jeder Änderung: `python3 -m py_compile`, danach Kopie nach `/home/jacob/audio-inferno/gui/inferno_gui/ui/`.
- Commits auf `main`, Conventions wie bisher (`feat:`/`fix:` + beschreibender Text).

## Review Focus

1. **Zeilenüberlauf/Clipping bei 1000px Fensterbreite** (Radio-Texte, lange Interface-Namen) → Test behauptet `totalMinimumWidth() <= verfügbar` für alle 3 PTP-Zeilen (Task 1, Schritt 4).
2. **IP-Label verliert seine Farblogik** (grün/orange in `_on_interface_changed`) → Test behauptet `ip_label` sitzt in der Statusleiste (gleiches Widget-Objekt), manuelle Prüfung nach Interface-Wechsel (Task 1, Schritt 8).
3. **Sync-/Status-Updates laufen ins Leere** (`_update_status_panel` schreibt `ptp_state/offset/freq_label`) → Test behauptet, dass alle drei Labels in Zeile 3 sind; manueller Start/Stop-Test (Task 1, Schritt 8).
4. **Inferno-Notiz bricht bei halber Breite auf >2 Zeilen** und frisst den Höhengewinn → Test behauptet `height <= 2 * lineSpacing + 6` (Task 1, Schritt 4), Fallback-Text in Task 1, Schritt 3 hinterlegt.
5. **50/50-Verteilung prüfbar** → Test behauptet: Eltern-Layout beider Gruppen ist `QHBoxLayout` UND Breiten±6px gleich (nur Breitenvergleich allein würde auch bei vertikalem Stapel bestehen) (Task 1, Schritt 4).

---

### Task 1: Layout-Neuanordnung mit Offscreen-Smoke-Test

**Files:**
- Create: `tests/test_layout_smoke.py`
- Modify: `inferno_gui/ui/control_tab.py:83-316` (`init_ui`)
- Install-Copy: `/home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py`

**Interfaces:**
- Consumes: bestehende Widgets/Slots unverändert – `self.interface_combo`, `self.refresh_iface_btn`, `self.ptp_v1_radio`, `self.ptp_v2_radio`, `self.start_ptp_btn`, `self.stop_ptp_btn`, `self.sync_light`, `self.sync_label`, `self.ip_label`, `self.ptp_state_label`, `self.ptp_offset_label`, `self.ptp_freq_label`, `self.qpwgraph_btn`, `self.cable_btn`, `self.netaudio_btn`, `self.test_alsa_btn`.
- Produces (neue `self.`-Attribute, auf die der Test zugreift): `self.ptp_group: QGroupBox`, `self.inferno_group: QGroupBox`, `self.ptp_layout: QVBoxLayout`, `self.inferno_note: QLabel`. Alle bisherigen Attribute bleiben erhalten.

- [ ] **Step 1: Failing Test schreiben – `tests/test_layout_smoke.py`**

```python
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
    # 2) Genau 3 Zeilen, keine lose Widgets mehr in der PTP-Box
    assert pl.count() == 3, f"PTP box must have exactly 3 rows, has {pl.count()}"
    rows = []
    for i in range(pl.count()):
        item = pl.itemAt(i)
        assert item.layout() is not None, f"row {i} is a loose widget, expected a row layout"
        rows.append(item.layout())

    # 3) Keine Zeile läuft über die Boxbreite hinaus (kein Clipping).
    #    contentsRect() der Box liefert exakt die verfügbare Inhaltsbreite (462px bei 1000px Fenster).
    available = pl.contentsRect().width()
    for i, row in enumerate(rows):
        need = row.totalMinimumWidth()
        assert need <= available, \
            f"PTP row {i} needs {need}px but only {available}px available"

    # 4) Radios gekürzt, IEEE nur noch im Tooltip
    assert ct.ptp_v1_radio.text() == "PTPv1"
    assert ct.ptp_v2_radio.text() == "PTPv2"
    assert "IEEE 1588-2002" in ct.ptp_v1_radio.toolTip()
    assert "IEEE 1588-2008" in ct.ptp_v2_radio.toolTip()

    # 5) Zeile 2 = Start/Stop/Sync, Zeile 3 = IP+State+Offset+Freq-Statusleiste
    for w in (ct.start_ptp_btn, ct.stop_ptp_btn, ct.sync_light, ct.sync_label):
        assert rows[1].indexOf(w) != -1, f"{w} not in PTP row 2"
    for w in (ct.ip_label, ct.ptp_state_label, ct.ptp_offset_label, ct.ptp_freq_label):
        assert rows[2].indexOf(w) != -1, f"{w} not in status strip (row 3)"

    # 6) Inferno-Notiz passt bei halber Breite auf max. 2 Zeilen
    line = ct.inferno_note.fontMetrics().lineSpacing()
    assert ct.inferno_note.height() <= 2 * line + 6, \
        f"note wraps beyond 2 lines: {ct.inferno_note.height()}px vs 2x{line}px"

    print("PASS: layout smoke test")


if __name__ == "__main__":
    test_layout()
```

- [ ] **Step 2: Test laufen lassen → muss FAIL sein**

```bash
cd /home/jacob/codingProjekts/inferno-gui && QT_QPA_PLATFORM=offscreen python3 tests/test_layout_smoke.py
```
Expected: `AssertionError` (aktuell: vertikales Stapel-Layout → "PTP box not in a horizontal layout", `pl.count() == 4`, Attribute `ptp_group` fehlen → `AttributeError`). Bei `AttributeError` zuerst `self.ptp_group`/`self.inferno_group`/`self.ptp_layout`/`self.inferno_note` als Attribute anlegen (nur Naming, keine Logik), dann erneut laufen lassen und die restlichen `AssertionError`s beobachten.

- [ ] **Step 3: `init_ui()` in `inferno_gui/ui/control_tab.py` umbauen**

Konkrete Änderungen (Reihenfolge im Code):

1. **Attribute anlegen:** in Zeile ~91 `self.ptp_group = ptp_group` und `self.ptp_layout = ptp_layout`; in Zeile ~191 `self.inferno_group = inferno_group`; in Zeile ~267 `self.inferno_note = note`.
2. **Zeile 1 PTP (`iface_row`, Zeilen 95–120):** `QLabel("PTP Version:")` und das folgende `iface_row.addSpacing(16)` entfernen. Radios behalten; direkt nach der Radio-Erzeugung (Zeilen 110/111) setzen:
   ```python
   self.ptp_v1_radio = QRadioButton("PTPv1")
   self.ptp_v1_radio.setToolTip("IEEE 1588-2002")
   self.ptp_v2_radio = QRadioButton("PTPv2")
   self.ptp_v2_radio.setToolTip("IEEE 1588-2008")
   ```
3. **IP-Label aus eigener Zeile entfernen:** `ptp_layout.addWidget(self.ip_label)` (Zeile ~125) löschen.
4. **Zeile 3 PTP statt `status_grid` (Zeilen 174–185):**
   ```python
   status_strip = QHBoxLayout()
   status_strip.setSpacing(16)
   status_strip.addWidget(self.ip_label)
   status_strip.addWidget(self.ptp_state_label)
   status_strip.addWidget(self.ptp_offset_label)
   status_strip.addWidget(self.ptp_freq_label)
   status_strip.addStretch()
   ptp_layout.addLayout(status_strip)
   ```
   (`btn_row` mit Start/Stop/Sync bleibt unverändert und ist Zeile 2.)
5. **Nebeneinander statt untereinander:** `layout.addWidget(ptp_group)` (Zeile ~187) löschen; `layout.addWidget(inferno_group)` (Zeile ~286) ersetzen durch:
   ```python
   top_row = QHBoxLayout()
   top_row.setSpacing(10)
   top_row.addWidget(ptp_group, 1)
   top_row.addWidget(inferno_group, 1)
   layout.addLayout(top_row)
   ```
6. **Notiz-Fallback (nur wenn Schritt 4, Testpunkt 6, fehlschlägt):** Notiztext in Zeile ~264 kürzen auf:
   ```
   Note: Inferno activates automatically when an application opens the 'inferno' PCM device via PipeWire.
   ```

- [ ] **Step 4: Test erneut laufen lassen → muss PASS sein**

```bash
cd /home/jacob/codingProjekts/inferno-gui && QT_QPA_PLATFORM=offscreen python3 tests/test_layout_smoke.py
```
Expected: `PASS: layout smoke test` (Exit-Code 0). Schlägt Punkt 6 (Notiz) fehl → Schritt 3.6 anwenden, wiederholen. Schlägt Punkt 3 (Zeilenbreite) fehl → Mindestbreiten NICHT erhöhen; Radio-/Label-Texte prüfen und im Plan-Review melden.

- [ ] **Step 5: Kompilieren + installierte Variante aktualisieren**

```bash
cd /home/jacob/codingProjekts/inferno-gui && python3 -m py_compile inferno_gui/ui/control_tab.py && \
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py && \
QT_QPA_PLATFORM=offscreen python3 tests/test_layout_smoke.py
```
Expected: compiles OK, Datei kopiert, `PASS: layout smoke test`.

- [ ] **Step 6: Commit**

```bash
cd /home/jacob/codingProjekts/inferno-gui && git add inferno_gui/ui/control_tab.py tests/test_layout_smoke.py docs/superpowers/ && \
git commit -m "feat: PTP and Inferno boxes side by side (50/50), PTP box compacted to 3 rows"
```

- [ ] **Step 7: Manuelle Abnahme durch den Nutzer**

```bash
sudo /home/jacob/audio-inferno/gui/run_gui.sh
```
Prüfen: beide Boxen nebeneinander (50/50), GUI-Breite unverändert, keine abgeschnittenen Elemente, Log-Terminal ~4 Zeilen höher.

- [ ] **Step 8: Manuelle Funktionsprüfung (in derselben Sitzung)**

- Interface wechseln → `IP:`-Label in der Statusleiste wird grün/orange (Farblogik greift weiterhin).
- ▶ Start → Sync-Licht + `State/Offset/Freq` aktualisieren sich in der Statusleiste; ■ Stop → Buttons zurücksetzen.
- PTPv1/PTPv2 Radios umschalten und GUI neu starten → Auswahl wird gespeichert/geladen (`QSettings`).
- "Test ALSA Device" → läuft unverändert.
