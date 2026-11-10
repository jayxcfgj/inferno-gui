# Design: Radios in eigene Zeile + GUI-Breite auf Minimum

**Datum:** 2026-11-10
**Betroffene Dateien:** `inferno_gui/ui/control_tab.py` (init_ui), `inferno_gui/ui/main_window.py` (_load_window_state), `tests/test_layout_smoke.py`

## Intent

Radios `PTPv1`/`PTPv2` von der Interface-Zeile lösen und in eine eigene Zeile
**unter** die Interface-Auswahl, **über** die Start/Stop-Zeile legen (Ansatz 1:
nur umsortieren, kein Zeilen-Trimming). Anschließend die Fensterbreite auf die
**kleinstmögliche** Breite setzen – die, bis zu der man das Fenster mit der Maus
kleiner ziehen kann (Qt-Mindestbreite).

## Goals

- `ptp_layout` bekommt **4 Zeilen**: ① Interface+Combo+↻ ② Radios ③ Start/Stop+Sync ④ Statusleiste.
- Fenster öffnet mit der **Qt-Mindestbreite** (neu: ~775px, statt 1000px default).
- Gesamthöhe unverändert (Radios-Zeile nutzt den ~112px-Spielraum der PTP-Box).
- Offscreen-Smoke-Test deckt die neue Mindestbreite ab (kein Clipping am Minimum).

## Non-Goals

- Kein Trimming bestehender Zeilen (Sync-Label bleibt 140px – Ansatz 3 nicht gewählt).
- Kein manuelles Stretch-/Größen-Tuning der Boxen.
- Settings-Tab, Logik, Slots, installierter Kopier-Pfad unverändert.

## Constraints (gemessen)

- Zeilen-Minima nach dem Umzug: ① ~297px ② ~126px ③ **421px (breitenbestimmend)** ④ 310px.
- PTP-Box-Minimum: ~445px · Inferno-Box-Minimum: ~289px · ControlTab-Min: **~760px** · Fenster-Min: **~775px**.
- Radios-Text/Tooltip wie gehalten: `PTPv1`/`PTPv2`, IEEE im Tooltip.

## ⚠️ Konsequenz: 50/50 gilt am Minimum NICHT

Bei Fensterbreite = Minimum (~775px) kann Qt die Boxen nicht gleich teilen:
Minimums zuerst → **PTP ~445px, Inferno ~289px**. Gleichheit (50/50) setzt erst
ab ~916px ein. Die Weisung „Breite = kleinstmögliche" hat Vorrang (explizit
befohlen, auch nach Wahl von Weg 1); beim Aufziehen ≥916px gilt 50/50 wieder.

## Ansätze

1. **Gewählt (Weg 1 + Mindestbreite):** nur umsortieren + Breite auf Qt-Minimum.
   (`setGeometry`-Default irrelevant, da `_load_window_state` ohnehin gespeicherte
   Geometrie wiederherstellt.)
2. Verworfen (nicht gewählt): Mindestbreite + 50/50 → ~916px (breiter).
3. Verworfen (nicht gewählt): zusätzlich Sync-Label schmaler → ~840px (Trimming ausdrücklich nicht gewünscht).

## Umsetzungs-Details

- **`control_tab.py`:** `iface_row` verliert beide Radios (und deren `addStretch`
  bleibt dort); neue `radio_row = QHBoxLayout()` zwischen `iface_row` und
  `btn_row` mit `ptp_v1_radio`, `ptp_v2_radio`, `addStretch()`.
  Signalverdrahtung (`ptp_version_group`, `idToggled`) bleibt unverändert.
- **`main_window.py`:** nach `_load_window_state()` (Zeile 40) Breite erzwingen:
  ```python
  if not self.isMaximized():
      self.resize(self.minimumSizeHint().width(), self.height())
  ```
  (Position und Höhe bleiben wie gespeichert; Nutzer kann während der Sitzung
  größer ziehen – beim nächsten Start wird auf Minimum zurückgesetzt.)
- **`tests/test_layout_smoke.py`** anpassen:
  - PTP-Zeilen 3 → **4**; Radio-Membership wandert zu `rows[1]`, Start/Stop → `rows[2]`, Status → `rows[3]`.
  - Neue Prüfung: kein Zeilen-Overflow bei `minimumSizeHint().width() + 10` (Puffer gegen Rand-1px).
  - Notiz-Assertion: bei 1000px ≤2 Zeilen wie bisher; am Minimum ≤3 Zeilen.
  - 50/50-Prüfung bleibt bei 1000px (dort gilt sie weiterhin).
- Nach jeder Änderung: `py_compile`, Kopie nach `~/audio-inferno/gui/inferno_gui/ui/`,
  `pytest tests/`, `ruff`-Parität prüfen.
