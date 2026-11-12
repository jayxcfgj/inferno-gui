# Design: Sync-Status-Icons (Taskleiste + Tray)

Datum: 2026-11-12 · Status: zur Freigabe

## Intent

Das Taskleisten-Fenster-Icon und das Tray-Icon sollen den PTP-Sync-Zustand
live zeigen: **grün, sobald „Locked" erreicht ist, sonst rot**. Aktuell gibt
es nur ein statisches, einmal beim Start geladenes Icon – der Wechsel wurde
nie implementiert.

## Goals

- Icon wechselt **grün ab „Locked"** – dieselbe Schwelle wie das
  Display-Label: `state == 'SLAVE' and offset_ns is not None and offset_ns <= 200`.
- **Beide Icons** wechseln: Fenster-/Taskleisten-Icon UND Tray-Icon.
- Sonst (PTP gestoppt, kein Sync, Fehler, Offset > 200 ns): **schwarz/weiß**
  (`icon.png`, der bisherige Status-quo) – **kein** rotes Icon.
- Wechsel nur bei tatsächlichem Zustandswechsel (kein Setzen im 500-ms-Takt).

## Non-Goals / Anti-Goals

- Keine gelbe/„Syncing"-Zwischenstufe für Icons (nur rot/grün).
- Kein Wechsel der Anzeige-Logik im Control-Tab (Ampel/Label bleiben unberührt).
- Keine neuen Abhängigkeiten.

## Constraints

- Icons: Vektor-SVG (skaliert scharf auf HiDPI-Taskleisten).
- Verfügbare Assets: `inferno_gui/assets/icon.svg` (grüner Verlauf, existiert
  bereits), `icon.png` (schwarz/weiß, bleibt Start-/Fallback-Icon).
- Statusquelle: bereits vorhandenes Signal
  `ControlTab.status_changed(dict)` (gefeuert in `_emit_status()`),
  Payload enthält u. a. `state` und `offset_ns`.
- Installierte Kopie `/home/jacob/audio-inferno/gui/` muss nach jedem Fix per
  `diff -rq --exclude=__pycache__ --exclude=*.toml` synchron gehalten werden.

## Ansätze

**A – Zwei vorhandene Icons + Laufzeit-Swap (gewählt)**
Bestehende Paarung nutzen: `icon.png` (schwarz/weiß) = nicht sync,
`icon.svg` (grün) = Locked. **Keine neue Asset-Datei.** MainWindow hört auf
`status_changed` und setzt bei Zustandswechsel `app.setWindowIcon()` (via
`QApplication.instance()`) und `self.tray_icon.setIcon()`. Icon-QObjekte werden
einmalig gecacht.
- Pro: keine neuen Dateien, nutzt beides Vorhandene, minimaler Code.

**B – Programmatisches Einfärben (Tint)**
Bestehendes Icon zur Laufzeit über den Alpha-Kanal einfärben. Keine neue Datei,
aber eigene Mal-Logik und aufwändigere Tests – überflüssig, da zwei fertige
Icons existieren.

**C – Dritte Variante (rot) erzeugen**
Nur relevant, wenn Rot statt Schwarz/Weiß gewünscht wäre – vom User
ausdrücklich abgelehnt.

B und C verworfen zugunsten von A (zwei fertige Icons vorhanden).

## Umsetzung (die Teile des How)

1. **Assets (keine neuen Dateien):** „nicht sync" = `icon.png`
   (schwarz/weiß, bisheriges Standard-Icon), „Locked" = `icon.svg` (grün).
2. **MainWindow:** Einzeiler
   `self.control_tab.status_changed.connect(self._on_sync_status)`.
   Cache: `self._icon_locked` / `self._icon_not_sync` (einmalig laden),
   Merker `self._sync_icons_locked: bool | None = None`.
3. **Handler** `_on_sync_status(status: dict)`: berechne
   `green = status.get('state') == 'SLAVE' and status.get('offset_ns') is not None
   and status.get('offset_ns') <= 200` (identisch zur „Locked"-Logik);
   nur wenn `green != self._sync_icons_locked`: Merker aktualisieren,
   `QApplication.instance().setWindowIcon(...)`,
   `self.tray_icon.setIcon(...)`.
4. **Startzustand:** schwarz/weiß = `icon.png` (Merker `False`), entspricht
   dem heutigen Verhalten – beim ersten Locked-Wechsel wird grün.

## Was dem Builder überlassen bleibt

- Exakte SVG-Erstellung (aus `icon.svg` ableiten, Verlaufsfarben wie oben).
- TDD-Test: Signal-Payload → Icon-Wechsel (Mock/QIcon-Vergleich via
  `cacheKey()`), plus Grenzwert-Test (200 ns grün, 201 ns schwarz/weiß,
  `offset_ns=None` schwarz/weiß, `state != 'SLAVE'` schwarz/weiß),
  QSettings auf Temp, keine echten Prozesse.
- Verifikation: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest
  tests/ -q`, ruff-Parität (Basis ≤ 277), Sync der installierten Kopie.
