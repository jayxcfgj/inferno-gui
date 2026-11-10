# Kompaktere PTP-Box (Leerräume) + Inferno-Statuszeile entfernen – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die PTP-Zeilen über die volle Boxbreite verteilen (Ansatz A), die PTP-Box oben ausrichten (AlignTop) und die tote „● Inferno: Stopped"-Zeile entfernen.

**Architecture:** In `ControlTab.init_ui()` bekommen Zeile 0 (Combo mit Stretch 1, abschließendes `addStretch()` raus), Zeile 1 (Spacer vor + nach den Radios) und Zeile 3 (3× `addStretch(1)` zwischen den Labels, abschließendes `addStretch()` raus) ihre neue Verteilung; `top_row.addWidget(ptp_group, 1)` bekommt `Qt.AlignmentFlag.AlignTop`; der Inferno-Statuszeilen-Block entfällt komplett. Signale/Slots/QSettings unverändert.

**Tech Stack:** Python 3, PyQt6; Tests via pytest im venv `/tmp/opencode/inferno-dev`.

**Spec:** `docs/superpowers/specs/2026-11-10-compact-ptp-rows-design.md`

## Global Constraints

- **Kein Trimming:** Sync-Label bleibt `setMinimumWidth(140)`, Combo-Minimum bleibt 200px, Radio-Texte/Tooltips (`PTPv1`/`PTPv2`, IEEE im Tooltip) unverändert → **Fenster-Mindestbreite bleibt 764px** (Start/Stop-Zeile 421px bleibt breitenbestimmend).
- Start/Stop-Zeile (`btn_row`) unverändert – inkl. abschließendem `addStretch()`.
- Kein funktionaler Eingriff: alle Widgets bleiben dieselben Objekte, Signale (`ptp_version_group`, `idToggled`), QSettings-Pfade und Slots unverändert; **einziger entfernter Code:** `inferno_status_label`/`inf_status_row` (statischer Text, grep: keine anderen Referenzen).
- Dateien: **nur** `inferno_gui/ui/control_tab.py` und `tests/test_layout_smoke.py`. Settings-Tab, `main_window.py`, Icons unverändert.
- Nach `py_compile`: **beide** geänderten Dateien? Nein – nur `control_tab.py` wird installiert; Test-Datei nicht. Kopie: `cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/` + `diff -q`.
- Verifikation: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q` → grün (3 Tests: `test_layout`, `test_main_window_clamp` + …); `ruff check tests/ inferno_gui/ui/control_tab.py inferno_gui/ui/main_window.py` → Parität zur Basis **`d5c865b`** (keine neuen Findings, gleiche Rule-Histogramme; Zeilennummern dürfen sich verschieben).
- Commit-Message: `feat: distribute PTP rows across box width, top-align PTP box, drop static Inferno status line`.

## Review Focus

1. **AlignTop darf die horizontale 50/50-Verteilung nicht zerstören** (Alignment wirkt auf beide Achsen, falls falsch gesetzt) → bestehende Assertion `abs(ptp_group.width()-inferno_group.width()) <= 6` bei 1000px muss grün bleiben; bei Misserfolg: BLOCKED melden, nicht „fixen".
2. **Statuszeilen-Mindestbreite wächst durch Spacing** (jetzt 6 Lücken ×16 statt 3×16 → ~358px statt 310px) → darf die Start/Stop-Zeile (421px) nicht übertreffen, sonst verschiebt sich das Fenster-Minimum → Clipping-Assertion bei 764px + `minimumSizeHint().width()==764` (über Clamp-Test implizit) decken das ab.
3. **Combo-Stretch darf bei keiner Breite unter 200px rutschen** → `totalMinimumSize`-Assertions (1000px + 764px) decken das ab.
4. **Entfernte Statuszeile darf nirgends referenziert werden** → `hasattr`-Assertion (RED) + `py_compile` + Lauf-Test; Logik-Referenzen wären zur Laufzeit ein `AttributeError`.
5. **Radios zentriert + Freq reicht bis zur Kante** (Kern von Ansatz A) → neue Spacer-/Membership-Assertions; Radio-Signale/QSettings-Loop weiterhin manuell (Schritt 7).

---

### Task 1: Verteilung + AlignTop + Statuszeile entfernen

**Files:**
- Modify: `tests/test_layout_smoke.py` (nach Block 5, Zeile ~82, vor Block 6 „Inferno-Notiz")
- Modify: `inferno_gui/ui/control_tab.py` (5 Stellen, siehe Step 3)
- Install-Copy: `/home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py`

**Interfaces:**
- Consumes: unverändert – `self.interface_combo`, `self.refresh_iface_btn`, `self.ptp_v1_radio`, `self.ptp_v2_radio`, `self.ip_label`, `self.ptp_state_label`, `self.ptp_offset_label`, `self.ptp_freq_label`, `self.ptp_group`, `self.inferno_group`, `self.ptp_layout`, `self.inferno_note`.
- Produces: **keine** neuen Attribute. `self.inferno_status_label` **entfällt** (Attribut gibt es nicht mehr). `ptp_layout` bleibt bei 4 Zeilen; Zeileninhalte/Reihenfolge unverändert, nur Verteilung anders.

- [ ] **Step 1: Test erweitern (RED)**

In `tests/test_layout_smoke.py`, in `test_layout()`, **direkt nach Block 5** (Zeile ~82, dem Loop `for w in (ct.ip_label, …)`, „status strip (row 3)") und **vor Block 6** („Inferno-Notiz passt…") einfügen – alle Prüfungen laufen dann noch bei 1000px, vor dem Resize aufs Minimum:

```python
    # 6) Inferno-Statuszeile entfernt (war statisch – wird nie aktualisiert)
    assert not hasattr(ct, "inferno_status_label"), "static Inferno status line must be gone"

    # 7) Ansatz A: Zeilen füllen die Boxbreite aus (bei 1000px)
    # Zeile 0: Combo wächst über ihr 200px-Minimum hinaus (kein Loch vor ↻)
    assert ct.interface_combo.width() > ct.interface_combo.minimumWidth(), \
        f"combo does not stretch: {ct.interface_combo.width()}px"
    # Zeile 1: Radios als Paar zentriert (Spacer links und rechts)
    assert rows[1].itemAt(0).spacerItem() is not None, "radio row missing left spacer (not centered)"
    assert rows[1].itemAt(rows[1].count() - 1).spacerItem() is not None, \
        "radio row missing right spacer (not centered)"
    # Zeile 3: 3 Spacer zwischen den 4 Labels, freq letztes Item → reicht bis zur Kante
    assert rows[3].count() >= 7, f"status strip not distributed: {rows[3].count()} items"
    assert rows[3].indexOf(ct.ptp_freq_label) == rows[3].count() - 1, \
        "freq label not last (trailing hole on the right)"
    # AlignTop: PTP-Box kürzer als Inferno-Box (nicht auf deren Höhe gezogen)
    assert ct.ptp_group.height() < ct.inferno_group.height(), \
        f"PTP box stretched to Inferno height: {ct.ptp_group.height()} vs {ct.inferno_group.height()}"
```

Die nachfolgenden Nummern der Bestandsblöcke (6→Notiz, 7→Min-Breite) unangetastet lassen (Kommentarnummern sind rein optisch; Verschieben optional).

- [ ] **Step 2: Test laufen lassen → muss FAIL sein**

```bash
cd /home/jacob/codingProjekts/inferno-gui && QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -v
```
Expected: FAIL mit `static Inferno status line must be gone` (die neue Assertion ist die erste, die noch nicht erfüllt ist; alle Alt-Assertions laufen weiter grün).

- [ ] **Step 3: `control_tab.py` – fünf exakte Edits**

**3.1 Combo-Stretch (Zeile 102):**
```python
# alt
        iface_row.addWidget(self.interface_combo)
# neu
        iface_row.addWidget(self.interface_combo, 1)
```

**3.2 Abschließendes Stretch in iface_row raus (Zeilen 119–120):**
```python
# alt
        iface_row.addStretch()
        ptp_layout.addLayout(iface_row)
# neu
        ptp_layout.addLayout(iface_row)
```

**3.3 Radio-Zeile zentrieren (Zeilen 123–127):**
```python
# alt
        radio_row = QHBoxLayout()
        radio_row.addWidget(self.ptp_v1_radio)
        radio_row.addWidget(self.ptp_v2_radio)
        radio_row.addStretch()
        ptp_layout.addLayout(radio_row)
# neu
        radio_row = QHBoxLayout()
        radio_row.addStretch()
        radio_row.addWidget(self.ptp_v1_radio)
        radio_row.addWidget(self.ptp_v2_radio)
        radio_row.addStretch()
        ptp_layout.addLayout(radio_row)
```

**3.4 Status-Labels verteilen (Zeilen 188–192), `status_strip.setSpacing(16)` bleibt:**
```python
# alt
        status_strip.addWidget(self.ip_label)
        status_strip.addWidget(self.ptp_state_label)
        status_strip.addWidget(self.ptp_offset_label)
        status_strip.addWidget(self.ptp_freq_label)
        status_strip.addStretch()
# neu
        status_strip.addWidget(self.ip_label)
        status_strip.addStretch(1)
        status_strip.addWidget(self.ptp_state_label)
        status_strip.addStretch(1)
        status_strip.addWidget(self.ptp_offset_label)
        status_strip.addStretch(1)
        status_strip.addWidget(self.ptp_freq_label)
```

**3.5 PTP-Box AlignTop (Zeile 296):**
```python
# alt
        top_row.addWidget(ptp_group, 1)
# neu
        top_row.addWidget(ptp_group, 1, Qt.AlignmentFlag.AlignTop)
```
(`Qt` ist importiert, Zeile 13.)

**3.6 Inferno-Statuszeile komplett entfernen (Zeilen 201–207):**
```python
# alt
        # Status row
        inf_status_row = QHBoxLayout()
        self.inferno_status_label = QLabel("● Inferno: Stopped")
        self.inferno_status_label.setStyleSheet("font-size: 13px; color: #888;")
        inf_status_row.addWidget(self.inferno_status_label)
        inf_status_row.addStretch()
        inferno_layout.addLayout(inf_status_row)

        # Tools group (NetAudio, qpwgraph, Cable – stacked vertically)
# neu
        # Tools group (NetAudio, qpwgraph, Cable – stacked vertically)
```

Danach:
```bash
cd /home/jacob/codingProjekts/inferno-gui && python3 -m py_compile inferno_gui/ui/control_tab.py
```
Expected: kompiliert OK.

- [ ] **Step 4: Test → muss PASS sein**

```bash
cd /home/jacob/codingProjekts/inferno-gui && QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -v
```
Expected: `2 passed`.

Fallbacks (falls eine Assertion fehlschlägt – im Report begründen, minimale Korrektur, keine Feature-Drift):
- `combo does not stretch` → prüfen ob 3.1 griff und 3.2 das Rest-Stretch entfernte (nicht beides behalten).
- `status strip not distributed` → prüfen ob 3.4 drei `addStretch(1)` hinterließ und das alte entfernt wurde.
- `PTP box stretched to Inferno height` → prüfen ob 3.5 griff; **nicht** die Assertion lockern, wenn der Edit fehlt.
- 50/50 bei 1000px schlägt fehl → **BLOCKED** melden (AlignTop-Interaktion, braucht Ruling).
- Clipping bei 764px schlägt fehl (Statuszeile >421px) → **BLOCKED** melden.

- [ ] **Step 5: Lint-Parität + installierte Variante aktualisieren**

```bash
cd /home/jacob/codingProjekts/inferno-gui && \
mkdir -p /tmp/ruffbase && \
git show d5c865b:tests/test_layout_smoke.py > /tmp/ruffbase/test_layout_smoke.py && \
git show d5c865b:inferno_gui/ui/control_tab.py > /tmp/ruffbase/control_tab.py && \
git show d5c865b:inferno_gui/ui/main_window.py > /tmp/ruffbase/main_window.py && \
git show d5c865b:pyproject.toml > /tmp/ruffbase/pyproject.toml && \
(/tmp/opencode/inferno-dev/bin/ruff check /tmp/ruffbase/ 2>/dev/null | grep -oE '^[A-Z][0-9]+' | sort | uniq -c) > /tmp/ruff_before.txt; \
(/tmp/opencode/inferno-dev/bin/ruff check tests/ inferno_gui/ui/control_tab.py inferno_gui/ui/main_window.py 2>/dev/null | grep -oE '^[A-Z][0-9]+' | sort | uniq -c) > /tmp/ruff_after.txt; \
diff /tmp/ruff_before.txt /tmp/ruff_after.txt && echo "ruff parity OK" && \
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/ && \
diff -q inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py && echo "installed copy synced"
```
Expected: `ruff parity OK` (identische Rule-Histogramme Basis `d5c865b` vs. Neu; Zeilennummern dürfen abweichen) und `installed copy synced`.
(Die Basis-Dateien liegen in `/tmp/ruffbase/` mit kopiertem `pyproject.toml`, damit dieselben Regeln gelten. Alternativ: `git stash` → ruff → `git stash pop` → ruff, Histogramme vergleichen.)

- [ ] **Step 6: Commit**

```bash
cd /home/jacob/codingProjekts/inferno-gui && \
git add inferno_gui/ui/control_tab.py tests/test_layout_smoke.py docs/superpowers/ && \
git commit -m "feat: distribute PTP rows across box width, top-align PTP box, drop static Inferno status line"
```

- [ ] **Step 7: Manuelle Abnahme durch den Nutzer**

```bash
sudo /home/jacob/audio-inferno/gui/run_gui.sh
```
- Kein Loch rechts in der PTP-Box: Combo reicht bis ↻, Radios mittig, Status-Labels verteilt (Freq rechts).
- Statuszeile kompakt (kein großes Loch mehr darüber/darunter); PTP-Box kürzer als Inferno-Box.
- „● Inferno: Stopped" ist weg.
- Interface-Wechsel, ▶/■ + Sync, PTPv1/v2-Umschalten + Neustart (QSettings), „Test ALSA Device" unverändert.
