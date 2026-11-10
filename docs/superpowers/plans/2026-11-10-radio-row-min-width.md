# Radios in eigene Zeile + GUI auf Mindestbreite – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die PTP-Radios in eine eigene Zeile unter die Interface-Auswahl legen (4 Zeilen in der PTP-Box) und die Fensterbreite beim Öffnen auf die Qt-Mindestbreite setzen.

**Architecture:** In `ControlTab.init_ui()` wandern `ptp_v1_radio`/`ptp_v2_radio` aus `iface_row` in eine neue `radio_row` zwischen `iface_row` und `btn_row` (Signale/QButtonGroup bleiben unverändert). In `MainWindow.__init__` wird nach `_load_window_state()` die Breite per `resize(minimumSizeHint().width(), height)` erzwungen (außer maximiert). Der Offscreen-Smoke-Test wird auf 4 Zeilen umgestellt und prüft zusätzlich kein-Clipping am Minimum.

**Tech Stack:** Python 3, PyQt6; Tests als plain `python3`/pytest-Skript (pytest im `dev`-Extra des Projekts, im venv `/tmp/opencode/inferno-dev` installiert).

**Spec:** `docs/superpowers/specs/2026-11-10-radio-row-min-width-design.md`

## Global Constraints

- Zeilen-Minima nach dem Umzug (gemessen): ① Interface ~297px ② Radios ~126px ③ **Start/Stop+Sync 421px (breitenbestimmend)** ④ Statusleiste 310px.
- PTP-Box-Minimum ~445px, Inferno-Box-Minimum ~289px, ControlTab-Minimum ~760px, Fenster-Minimum ~764px (gemessen; Schätzung war ~775px).
- Radio-Texte exakt `PTPv1`/`PTPv2`, IEEE nur als Tooltip (`IEEE 1588-2002`/`IEEE 1588-2008`) – unverändert vom letzten Task.
- **Kein** Trimming bestehender Zeilen (Sync-Label bleibt `setMinimumWidth(140)`, Combo bleibt 200px), **kein** manuelles Stretch-/Größen-Tuning der Boxen.
- Clamp-Regel: `if not self.isMaximized(): self.resize(self.minimumSizeHint().width(), self.height())` – **nach** `_load_window_state()`. Höhe und Position weiterhin aus QSettings.
- Dateien: **nur** `inferno_gui/ui/control_tab.py`, `inferno_gui/ui/main_window.py`, `tests/test_layout_smoke.py`. Settings-Tab/Logik/Icons unverändert.
- Nach jeder Änderung beider Dateien: `python3 -m py_compile`; danach **beide** nach `/home/jacob/audio-inferno/gui/inferno_gui/ui/` kopieren.
- Verifikation: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q` → grün; `ruff check` auf dieselben Dateien → Parität zur Vor-Version (keine neuen Findings; Basis: `1aeb0af`).
- 50/50 der Boxen gilt weiterhin **bei 1000px** (Test prüft das dort); am Minimum sind die Boxen ungleich (PTP ~445 / Inferno ~289) – das ist so gewollt, kein Defekt.

## Review Focus

1. **Clamp greift in beiden Pfaden** (gespeicherte Geometrie vorhanden vs. frisches `setGeometry(…,1000,…)`) und wird **nicht** angewendet, wenn das Fenster maximiert ist → manuelle Prüfung in Task-1-Schritt 8; Code-Lage: Aufruf muss nach Zeile 40 (`_load_window_state`) stehen.
2. **Radio-Signale nach dem Umzug intakt** (`ptp_version_group.addButton(..., 1/2)`, `idToggled`, `QSettings("InfernoGUI","control")` ptp_version) → Test behauptet Membership von `ptp_v1_radio`/`ptp_v2_radio` in `rows[1]`; Speicher-Lade-Zyklus manuell in Schritt 8.
3. **Neue Mindestbreiten-Prüfung nicht vakuell** (`contentsRect() > 0` vor dem Vergleich, Rows werden nach Resize neu vermessen) → Test schlägt bei Clipping fehl; RED-Nachweis in Schritt 2.
4. **Notiz-Zeilenzahl:** bei 1000px ≤2 Zeilen (bestehende Assertion), am Minimum ≤3 Zeilen (neue Assertion) → beide im Test.
5. **50/50-Assertion bei 1000px bleibt gültig** und darf durch den Umzug nicht zerfallen → bestehender Testpunkt, muss weiter grün sein.

---

### Task 1: Radios-Zeile + Mindestbreite inkl. Test-Update

**Files:**
- Modify: `tests/test_layout_smoke.py`
- Modify: `inferno_gui/ui/control_tab.py` (~Zeilen 94–190, `init_ui`)
- Modify: `inferno_gui/ui/main_window.py` (Zeile 40)
- Install-Copy: `/home/jacob/audio-inferno/gui/inferno_gui/ui/{control_tab,main_window}.py`

**Interfaces:**
- Consumes: bestehende Attribute unverändert – `self.ptp_v1_radio`, `self.ptp_v2_radio`, `self.ptp_version_group`, `self.interface_combo`, `self.refresh_iface_btn`, `self.start_ptp_btn`, `self.stop_ptp_btn`, `self.sync_light`, `self.sync_label`, `self.ip_label`, `self.ptp_state_label`, `self.ptp_offset_label`, `self.ptp_freq_label`, `self.ptp_group`, `self.inferno_group`, `self.ptp_layout`, `self.inferno_note`.
- Produces: **keine** neuen Attribute. `self.ptp_layout` enthält ab jetzt **4** Layout-Zeilen in dieser Reihenfolge: iface_row, radio_row, btn_row, status_strip.

- [ ] **Step 1: Test auf den neuen Vertrag umstellen (RED)**

In `tests/test_layout_smoke.py` innerhalb `test_layout()` ändern:

1. Zeilenzahl + Membership (ersetzt die alten 3-Zeilen-Blöcke):
```python
    pl = ct.ptp_layout
    # 4 Zeilen, keine lose Widgets
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

    # Zeile 2: Start/Stop/Sync, Zeile 3: Statusleiste
    for w in (ct.start_ptp_btn, ct.stop_ptp_btn, ct.sync_light, ct.sync_label):
        assert rows[2].indexOf(w) != -1, f"{w} not in PTP row 2"
    for w in (ct.ip_label, ct.ptp_state_label, ct.ptp_offset_label, ct.ptp_freq_label):
        assert rows[3].indexOf(w) != -1, f"{w} not in status strip (row 3)"
```
(Alt-Blöcke mit `rows[1]`/`rows[2]` entsprechend an die neue Indizierung anpassen; die Radio-Text/Tooltip-Assertions bei ~Zeile 58 bleiben unverändert.)

2. Bestehende Clipping-Prüfung (Zeile ~51) behalten sie NUR für 1000px (Umgebungs-Var `available`), **danach** neue Mindestbreiten-Prüfung anhängen:
```python
    # Am kleinstmöglichen Fenster darf keine Zeile abschneiden
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
```
Reihenfolge im Test: erst die 1000px-Prüfungen (50/50, Notiz ≤2, Clipping), DANN auf Minimum resizen (danach gelten die 1000px-Assertions bereits als ausgeführt). Am Ende das bestehende `print("PASS: ...")`.

- [ ] **Step 2: Test laufen lassen → muss FAIL sein**

```bash
cd /home/jacob/codingProjekts/inferno-gui && QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -v
```
Expected: FAIL mit `PTP box must have exactly 4 rows, has 3` (beweist, dass die neue Assertion greift).

- [ ] **Step 3: `control_tab.py` – Radios in eigene Zeile**

- Aus `iface_row` (Zeilen ~95–120) die drei Zeilen
  `iface_row.addWidget(self.ptp_v1_radio)` und `iface_row.addWidget(self.ptp_v2_radio)` entfernen (die Radio-Erzeugung samt Tooltips bleibt, wo sie ist).
- Direkt nach `ptp_layout.addLayout(iface_row)` eine neue Zeile einfügen:
```python
        # PTP version radios (own row: below interface, above start/stop)
        radio_row = QHBoxLayout()
        radio_row.addWidget(self.ptp_v1_radio)
        radio_row.addWidget(self.ptp_v2_radio)
        radio_row.addStretch()
        ptp_layout.addLayout(radio_row)
```
- `python3 -m py_compile inferno_gui/ui/control_tab.py`

- [ ] **Step 4: `main_window.py` – Breite auf Minimum setzen**

Nach Zeile 40 (`self._load_window_state()`) einfügen:
```python
        # Open at the smallest possible width (per spec; height/position stay saved)
        if not self.isMaximized():
            self.resize(self.minimumSizeHint().width(), self.height())
```
- `python3 -m py_compile inferno_gui/ui/main_window.py`

- [ ] **Step 5: Test → muss PASS sein**

```bash
cd /home/jacob/codingProjekts/inferno-gui && QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -v
```
Expected: `1 passed`.
Fallbacks (falls eine Assertion fehlschlägt):
- Notiz >3 Zeilen am Minimum → Notiztext NICHT ändern; erst `print`-Diagnose (Zeilenhöhe/Zeichenzahl), dann Assertion auf die gemessene reale Zeilenzahl anheben und im Report begründen.
- Clipping-Assertion fehlschlägt (1-2px) → `resize(minimumSizeHint().width() + 10, 750)` und im Report vermerken; Zeilen-Texte/NICHT Mindestbreiten ändern.
- 50/50 bei 1000px schlägt fehl → abbrechen und BLOCKED melden (dann wurde die Struktur falsch umgesetzt).

- [ ] **Step 6: Lint-Parität + installierte Variante aktualisieren**

```bash
cd /home/jacob/codingProjekts/inferno-gui && \
/tmp/opencode/inferno-dev/bin/ruff check tests/ inferno_gui/ui/control_tab.py inferno_gui/ui/main_window.py > /tmp/ruff_after.txt; \
git stash -q && /tmp/opencode/inferno-dev/bin/ruff check tests/ inferno_gui/ui/control_tab.py inferno_gui/ui/main_window.py > /tmp/ruff_before.txt; git stash pop -q; \
diff /tmp/ruff_before.txt /tmp/ruff_after.txt && echo "ruff parity OK" && \
cp inferno_gui/ui/control_tab.py inferno_gui/ui/main_window.py /home/jacob/audio-inferno/gui/inferno_gui/ui/ && \
diff -q inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py && \
diff -q inferno_gui/ui/main_window.py /home/jacob/audio-inferno/gui/inferno_gui/ui/main_window.py && echo "installed copy synced"
```
Expected: `ruff parity OK` (identische Findings-Sets vorher/nachher) und `installed copy synced`.
(Hinweis: `git stash` legt die Änderungen für den Vorher-Vergleich zurück – sicherstellen, dass danach `git stash pop` liefert; alternativ die Vor-Version via `git show 1aeb0af:<path>` nach `/tmp` legen und ruff mit `--config pyproject.toml` darauf laufen lassen.)

- [ ] **Step 7: Commit**

```bash
cd /home/jacob/codingProjekts/inferno-gui && \
git add inferno_gui/ui/control_tab.py inferno_gui/ui/main_window.py tests/test_layout_smoke.py docs/superpowers/ && \
git commit -m "feat: PTP radios in own row below interface, window opens at minimum width"
```

- [ ] **Step 8: Manuelle Abnahme durch den Nutzer**

```bash
sudo /home/jacob/audio-inferno/gui/run_gui.sh
```
- Fenster öffnet schmal (~764px, gemessen; Schätzung war ~775px), nichts abgeschnitten, Höhe unverändert.
- PTPv1/v2 auswählen, GUI neu starten → Auswahl bleibt (QSettings-Loop).
- Aufziehen ≥916px → beide Boxen gleich breit (50/50); Fenster zu + neu öffnen → wieder Minimum.
- Interface-Wechsel, Start/Stop-Sync, "Test ALSA Device" unverändert.
