# Design: Kompaktere PTP-Box (Leerräume weg) + Inferno-Statuszeile entfernen

**Datum:** 2026-11-10
**Betroffene Dateien:** `inferno_gui/ui/control_tab.py` (`init_ui`), `tests/test_layout_smoke.py`

## Intent

Drei optische Leerräume in der Control-Tab schließen:
1. **Rechts in der PTP-Box:** Zeilen stoppen bei ungleicher Breite → Inhalte über die volle Breite verteilen (**Ansatz A**, vom User gewählt).
2. **Über/unter der Statuszeile:** PTP-Box wird auf Inferno-Box-Höhe gezogen (~110px Überschuss verteilen sich in die Zeilen; Statuszeile gemessen 74px hoch für ~16px Inhalt) → PTP-Box **oben ausrichten (AlignTop)**.
3. **„● Inferno: Stopped"-Zeile** in der Inferno-Box entfernen – die Zeile ist tot (`inferno_status_label` wird nirgends aktualisiert, zeigte also immer „Stopped").

## Goals

- PTP-Zeilen füllen die Boxbreite aus: Combo wächst bis ↻, Radios als Paar zentriert, Status-Labels gleichmäßig verteilt (frequenz rechts bis an die Kante).
- PTP-Box fällt auf ihre Inhaltsgröße (AlignTop) → Lücken über/unter der Statuszeile zurück auf Standardabstand (8px/Box-Margin).
- Inferno-Box ~28px kürzer (Statuszeile weg) → Gesamtfenster-Mindesthöhe sinkt leicht, mehr Platz fürs Log-Terminal.
- Kein funktionaler Eingriff: alle Widgets/Signale/QSettings-Pfade bleiben, wo sie sind.

## Non-Goals

- **Kein Trimming** bestehender Inhalte: Sync-Label bleibt 140px, Combo-Minimum 200px, Radio-Texte/Tooltips unverändert → **Fenster-Mindestbreite bleibt 764px**.
- Start/Stop-Zeile bleibt wie ist (füllt am Minimum bereits vollständig; kleiner Restspalt erst ab ~1000px Fensterbreite – akzeptiert).
- Keine Änderungen an Settings-Tab, Logik, Icons, installiertem Kopierpfad-Verfahren.

## Constraints (gemessen, aktuell bei 764px)

- Box 445px breit, Inhaltsbreite 421px; Zeilenfüllung heute: ①~307 ②~128 ③421 ④~310 → Löcher rechts ①~114 ②~293 ④~111.
- PTP-Box-Höhe 264px (auf Inferno gestreckt), Inhalt natürlich ~160px.
- Start/Stop-Zeile (421px) bleibt breitenbestimmend → Fenster-Minimum unverändert.

## Approaches

| | Ansatz | Entscheidung |
|---|---|---|
| **A** | Inhalte über volle Breite verteilen | **gewählt (User)** |
| B | Nur Radios zentriert | verworfen – Kosmetik, Löcher ①/④ blieben |
| C | Box schmaler via Trimmen (Sync 140→~80) | verworfen – löst „rechts" für andere Zeilen nicht, Trimming unerwünscht |

Vertikal: **AlignTop** (einzig Weg, Lücke über *und* unter der Statuszeile gleichzeitig zu beseitigen; Alternative „gleiche Höhe + Stretch" verschiebt die Lücke nur). Konsequenz: Boxen ungleich hoch – vom User bei der Freigabe nicht widersprochen.

## Umsetzungs-Details (`control_tab.py`, `init_ui`)

1. **Zeile 0 (iface_row):** `addWidget(self.interface_combo)` → `addWidget(self.interface_combo, 1)`; abschließendes `iface_row.addStretch()` (Zeile 119) **entfernen** → Combo wächst, ↻ steht rechts am Rand.
2. **Zeile 1 (radio_row):** Reihenfolge zu `addStretch()`, `ptp_v1_radio`, `ptp_v2_radio`, `addStretch()` → Paar mittig, symmetrische Lücken.
3. **Zeile 3 (status_strip):** `ip, addStretch(1), state, addStretch(1), offset, addStretch(1), freq`; abschließendes `addStretch()` (Zeile 192) **entfernen** → Labels gleichmäßig verteilt, Freq rechts an der Kante.
4. **AlignTop:** `top_row.addWidget(ptp_group, 1)` (Zeile 296) → `top_row.addWidget(ptp_group, 1, Qt.AlignmentFlag.AlignTop)` (Qt-Import existiert). Horizontal-Verteilung/50/50 unberührt (Alignment betrifft nur die vertikale Achse – verifiziert über die bestehende 50/50-Assertion).
5. **Inferno-Statuszeile entfernen:** Block Zeilen 201–207 (`inf_status_row` + `self.inferno_status_label`) komplett löschen. Keine anderen Referenzen (grep: nur Erzeugung).

## Test-Update (`tests/test_layout_smoke.py`, RED → GREEN)

Bestehende Assertions bleiben alle gültig (4 Zeilen, Membership, 50/50 bei 1000px, Notiz ≤2/3 Zeilen, Clipping, Clamp-Test). Neu:

- `not hasattr(ct, "inferno_status_label")` – Statuszeile ist weg.
- Zeile 0: `interface_combo.width() > interface_combo.minimumWidth()` bei 1000px – Combo wächst.
- Zeile 1: erstes und letztes Item sind Spacer – Radios zentriert.
- Zeile 3: letztes Item ist `ptp_freq_label` **und** `count() >= 7` (3 Spacer zwischen den 4 Labels) – keine Restlücke rechts, Labels verteilt.
- `ct.ptp_group.height() < ct.inferno_group.height()` bei 1000px – AlignTop greift.

## Verifikation

- `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q` → grün.
- `ruff check`-Parität zur Basis (keine neuen Findings).
- Beide Dateien nach `/home/jacob/audio-inferno/gui/inferno_gui/ui/` kopieren, `diff -q` → byte-identisch.
- Manuelle Abnahme (User, `sudo …/run_gui.sh`): kein Loch rechts, Statuszeile kompakt, „Inferno: Stopped" weg, Radios/Start/Stop/Test-ALSA unverändert.
