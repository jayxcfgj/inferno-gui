# Design: PTP- und Inferno-Box nebeneinander (50/50)

**Datum:** 2026-11-10
**Betroffene Datei:** `inferno_gui/ui/control_tab.py` (`init_ui()`)

## Intent / Warum

Die PTP-Box und die Inferno-Box stehen heute untereinander und verbrauchen zusammen
~9 Zeilen Höhe. Nebeneinander spart das die Höhe von ~4–5 Zeilen, die dem
Log-Terminal (`stretch=1`) zugutekommen. Die Gesamtbreite der GUI bleibt unverändert.

## Goals

- Beide Boxen nebeneinander, exakt **50/50** Breite.
- PTP-Box auf **3 kompakte Zeilen** verdichten.
- GUI-Breite unverändert; Bedienung und Logik unverändert (keine Signale/Slots betroffen).
- Alle PTP-Elemente bleiben sichtbar und bedienbar.

## Non-Goals / Anti-Goals

- Keine Änderungen an Inferno-Box, Log-Terminal oder Settings-Tab.
- Keine funktionalen Änderungen (Start/Stop, Interface-Erkennung, Sync-Anzeige).
- Keine volle Breite der Buttons/Elemente in den Boxen erzwingen (siehe `16c1d04`).

## Constraints

- Kommandozeile/`SUDO_USER`-Verhalten und bestehende Icons bleiben unangetastet.
- Halbe Boxenbreite ≈ 500px: Zeile 1 muss mit `Interface:` + Combo + ↻ + zwei Radios
  darin passen → Combo-Mindestbreite ggf. von 200px auf ~150px senken,
  Radio-Texte von `PTPv1 (IEEE 1588-2002)` auf nur `PTPv1` / `PTPv2` kürzen
  (IEEE-Referenz wandert in den Tooltip).

## Ansätze (im Gespräch erwogen)

1. **Re-Flow (4 Zeilen):** nur Zeile 1 splitten, IP in die Versions-Zeile.
   Wenig Änderung, aber eine Zeile höher als nötig.
2. **Kompakt (3 Zeilen) – gewählt:** Elemente zusammenfassen, Radio-Texte kürzen,
   IP + State + Offset + Freq als eine Statusleiste. Spart eine weitere Zeile,
   dichter aber gut lesbar.

**Entscheidung:** Ansatz 2 (vom Nutzer bestätigt, inkl. Kürzung der Radio-Texte).

## Ergebnis-Layout

```
┌─ PTP Clock Synchronization (statime) ─┬─ Inferno ALSA Plugin ─────────────┐
│ [Interface: ▾][↻] ○PTPv1 ○PTPv2       │ ● Inferno: Stopped               │
│ [▶ Start] [■ Stop] ● Sync-Licht —     │ [🌐 Open NetAudio Web UI]        │
│ IP: … State: … Offset: … Freq: …      │ [Open qpwgraph]                  │
│                                        │ [Open Cable]                     │
│                                        │ Notiz…                           │
│                                        │ [Test ALSA Device (aplay -L)]    │
├─ Statime Log Output (filtered) ───────┴──────────────────────────────────┤
│ …Terminal (stretch=1, gewinnt ~4 Zeilen Höhe)…                          │
└──────────────────────────────────────────────────────────────────────────┘
```

- Neue `QHBoxLayout` (`top_row`) über `ptp_group` + `inferno_group`, je `stretch=1`.
- Zeile 1 PTP: Interface-Label + Combo + ↻ + Radios (`PTPv1`/`PTPv2`, IEEE im Tooltip).
  **Entscheidung nach Vermessung:** Das `PTP Version:`-Label entfällt, weil Zeile 1 sonst
  477px bräuchte (nur 462px verfügbar). Die Radios sind selbsterklärend, IEEE steht im Tooltip.
- Zeile 2 PTP: ▶ Start + ■ Stop + Sync-Licht + Sync-Label (unverändert).
- Zeile 3 PTP: `ip_label`, `ptp_state_label`, `ptp_offset_label`, `ptp_freq_label` als
  eine horizontale Statusleiste (gleiche Widgets, gleiche Slots → Logik unverändert).
- **Mein Call:** Der Notiz-Text der Inferno-Box wird ggf. leicht gekürzt, damit er bei
  halber Breite auf max. 2 Zeilen umbricht (sonst wächst die Box wieder).

## Vermessung (2026-11-10, offscreen bei 1000px Fensterbreite)

- Verfügbare Inhaltsbreite je Box: **462px** (Box-Außenbreite 492px).
- Zeile 1 ohne Versions-Label + Combo 200px + kurze Radios: **~435px** ✓
  (mit Label: 477px → passt nicht).
- Zeile 2 (Start/Stop/Sync): **~423px** ✓ · Zeile 3 (Statusleiste): **~328px** ✓
- Konsequenz: Combo-Mindestbreite bleibt **200px** (150px laut ursprünglichem Call nicht nötig).

## Offen für den Builder

- Ggf. Feintuning der Mindestbreiten (Combo 150px, Sync-Label), damit Zeile 1/2
  in der halben Breite nicht abgeschnitten wird – solange Layout und Logik gleich bleiben.
