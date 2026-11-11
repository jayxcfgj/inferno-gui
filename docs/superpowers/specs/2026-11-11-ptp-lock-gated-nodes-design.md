# PTP-Lock-Gated PipeWire-Nodes – Design

**Datum:** 2026-11-11 · **Status:** Entwurf (Freigabe ausstehend)

## Problem

`start_ptp()` erzeugt die PipeWire-Nodes (`_create_pipewire_nodes()`, control_tab.py:470)
**sofort** beim Start von statime – noch bevor ein PTP-Sync existiert. Ohne Lock hat das
inferno-ALSA-Device keine Uhr → `set_hw_params`-Timeout → Node fällt sofort in den
Error-Zustand (`no clock available` → `suspended -> error`).

## Recherche-Ergebnis (Grundlage der Parameter)

- **netaudio/Dante:** Kein ns-Grenzwert im Client-Code – der Status kommt vom Gerät
  selbst (`servo_state_code == 3` → "synchronized"). Ein ähnlicher Geräte-Status steht
  inferno **nicht** zur Verfügung.
- **inferno:** Nur binär (`freq_offset` vorhanden → „clock appeared", sonst „no clock
  available"); der `/* 0x01 = PLL not locked */`-Kommentar ist ein hardkodiertes Byte.
  Kein abfragbarer Lock-/Servo-Status.
- **Konsequenz:** Die GUI leitet den Lock weiterhin selbst aus dem statime-Log ab
  (State `SLAVE` + Offset) – vorhandene Parser-Logik (`get_sync_status()`).
- **Schwellwerte:** Clear-Com-Praxis (AES67/ST2110): ±100 ns exzellent, ±500 ns
  potenzielle Probleme, **±1000 ns Probleme wahrscheinlich**. linuxptp-Muster:
  Locked = Schwelle **× N aufeinanderfolgende Samples** (dort 10).

## Entscheidungen (vom User gewählt)

| Parameter | Wert |
|---|---|
| Ansatz | **A – Parser-basiert** (SLAVE + Offset aus statime-Log) |
| Schwellwert PTPv2 | **1000 ns** (AES67-Grenze) |
| Schwellwert PTPv1 | **1500 ns** (v1 ist weniger präzise) |
| Stabilität | **5 aufeinanderfolgende Status-Ticks** (Tick = 500 ms → ≈2,5 s) |
| Timeout | **Keiner** – Nodes entstehen, sobald Lock erreicht wird (auch nach Minuten) |

## Verhalten

### Start (`start_ptp`)
- Ruft `_create_pipewire_nodes()` **nicht mehr direkt** auf.
- Setzt Statemachine auf *Lock-Wartend*: Log „Waiting for PTP lock before creating
  PipeWire nodes…", ggf. mit Schwellwert-Hinweis.
- PTP-Start-Verfahren (sudo-Check, Config, `_verify_ptp_startup`) bleibt unverändert.

### Status-Tick (`_update_status_panel`, alle 500 ms)
Solange *Lock-Wartend* und PTP läuft:
1. `state == 'SLAVE'` und `offset_ns is not None` und `offset ≤ Schwelle(Version)`
   → Zähler + 1, sonst Zähler = 0.
2. Zähler ≥ 5 → **Lock erreicht**: Nodes werden erzeugt, Log
   „PTP locked (offset X ns, 5/5 ticks) – creating PipeWire nodes…", Wartend-Flag weg.
3. Ohne Lock: alle 10 s eine Statuszeile („still waiting for lock: state=…, offset=…ns"),
   damit das Log nicht schweigt.

### Abbruch / Stop
- PTP-Prozess stirbt, **bevor** Lock erreicht → Wartend-Flag zurücksetzen, Log
  „PTP exited before lock – no PipeWire nodes created".
- `stop_ptp()` → Wartend-Flag zurücksetzen, Nodes wie bisher zerstören (unverändert).
- **Non-Goal:** Lock-Verlust *nach* Node-Erzeugung führt **nicht** zum Node-Destroy
  (wie bisher – Nodes bleiben, bis Stop/Restart).

### Anzeige (unverändert)
Das „Locked"-Label/AMPel-Logik (≤200 ns „Locked", ≤1000 ns „Syncing…") bleibt **reine
Anzeige** und ändert sich nicht – Gate und Display sind getrennt.

## Mit-enthalten: Node-Erzeugungs-Fix (86d36dd-Regression)

Da wir `_create_pipewire_nodes` ohnehin anfassen:
- **Defekte Args raus:** `sink_cmd`/`source_cmd` enthalten literal `'{`/`'}`-Tokens
  (Zeile 533/544) – keine gültigen `key=value`-Paare → `object.linger=1` greift nie →
  Node stirbt mit pw-cli-Exit. **Fix:** schlichte `key=value`-Paare als eigene Args,
  `object.linger=1` zuerst, ohne Klammern/Apostrophe (verifiziert: beide Nodes
  persistieren).
- **Ehrliches Logging:** Exit-Code von pw-cli prüfen + anschließend `pw-cli ls Node`
  nach `Inferno_sink`/`Inferno_source` verifizieren; stderr auf `error` scannen.
  Nur bei voller Verifikation „created successfully", sonst klare ERROR-Meldung.

## Testansatz (TDD)

- **Neu, pure Logik:** `inferno_gui/core/lock_gate.py` – Klasse/Funktion
  `LockGate(threshold_ns, required_ticks)` mit `feed(state, offset_ns) -> bool`
  (True = Lock erreicht, einmalig). Tests: 5 Treffer unter Schwelle → True;
  Unterbrechung (Tick ohne Treffer) setzt zurück; falscher State setzt zurück;
  Offset-None setzt zurück; Schwellwert-V2 1000 vs. V1 1500.
- **Wiring:** `start_ptp` ruft Nodes nicht sofort auf (gemockt); Lock → genau ein
  Node-Aufruf; Stop setzt Wartend-Flag zurück.
- **Node-Args:** `sink_cmd`/`source_cmd` enthalten `object.linger=1`, keine `'`/`{`/`}`;
  Erfolgs-Log nur nach verifizierter Node-Existenz.
- Lauf: `QT_QPA_PLATFORM=offscreen pytest tests/ -q`, ruff-Parität zur Basis `9dd1c97`,
  installierte Kopie nach jedem Fix per `diff -q` synchron.

## Non-Goals

- Keine Änderung an Parser-Schwellwerten für die Anzeige.
- Kein Lock-Verlust-Handling nach Node-Erzeugung.
- Keine inferno- oder netaudio-Codeänderungen (nur GUI).
