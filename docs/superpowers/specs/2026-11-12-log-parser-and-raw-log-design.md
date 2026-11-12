# Spec: Log-Parser-Korrektur + „Filtered"-Rohlog-Checkbox

**Datum:** 2026-11-12 · **Status:** Entwurf (Freigabe ausstehend)

## Intent

Der gefilterte Log-View zeigt aus dem schnellen statime-Trace nicht immer
korrekte Werte (falsche Frequenz-Einheit, erratener State, veraltete
Metriken, zerbrochene Zeilen). Zusätzlich braucht man eine Checkbox neben
„Verbose", mit der man den gefilterten Log abschalten und den **echten**
Trace sehen kann – zur Kontrolle des Parses.

## Rohformat-Referenz (belegt, GUI-weit verbindlich)

```
2026-11-12T14:33:21.123456Z  TRACE statime::filters::kalman: Estimated offset -123.45ns+-12.3ns, freq 1.234+-0.567, delay 4567.8+-12.3
2026-11-12T14:33:21.123456Z  INFO  statime::port: new state for port 0: Listening -> Slave
2026-11-12T14:33:21.123456Z  ERROR statime::…: Could not adjust clock frequency
```

- Metrik-Quelle: **eine** TRACE-Zeile pro Messung (kalman.rs:680,
  `display_state()`), Frequenzwert ist `freq_offset()*1e6` = **ppm**,
  `delay`-Wert ist ns (ohne `ns`-Suffix im Format!).
- State-Übergänge: `new state for port <n>: <Alt> -> <Neu>` (port/mod.rs:658).
- Level-Präfix rechtsbündig 5-stellig: `TRACE/DEBUG/ INFO/ WARN/ERROR`.
- Timestamp: `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

## Constraints

- Direkt auf `main`, kein Worktree; TDD (RED→GREEN); ruff ≤ 277 (Basis
  `9dd1c97`); installierte Kopie nach jedem Fix synchron
  (`diff -rq --exclude=__pycache__ --exclude=*.toml`).
- **Keine** Änderungen an statime (nur inferno-gui).
- Locked-Definition bleibt: `ptp_state == 'SLAVE' and ptp_offset is not None
  and abs(ptp_offset) <= 200`.
- Schwellen-Buckets (≤200 / ≤1000) bleiben; **kein** Metrik-Timeout
  (Paket D vom User abgelehnt).
- Verbose-Checkbox und Anzeige-Logik (`_update_sync_light`-Struktur,
  Labels) bleiben in Funktion und Aufbau erhalten.

## Fehlerkatalog → Fixes

### A – Zeilensplitting (control_tab.py `_flush_terminal`)

Der 50-ms-Flush verarbeitet den Puffer inkl. unvollständiger Schlusszeile
und leert ihn; bei schnellem Trace wird mitten in der Zahl geteilt
(`Estimated offset -1` | `23.45ns…`).

**Fix:** In `_flush_terminal` nur bis zum **letzten `\n`** verarbeiten,
Residuum im Buffer belassen (analog stdout+stderr). Residuum-Limit 8 KB –
ohne `\n` danach trotzdem forciert verarbeiten (Zeilenschutz). Fix gilt
für **beide** Anzeigemodi (roh und gefiltert), da er auf Puffer-Ebene sitzt.

### B – State-Patterns & Metrik-Reset (log_parser.py)

Die `(?:to|entered) …`-Muster (Zeilen 72-107) matchen nie (statime loggt
`-> `), der State wird nur aus Metrik-Zeilen erraten (Zeilen 294-299) und
nie zurückgesetzt → nach Sync-Verlust bleiben Light/Icon/LockGate auf SLAVE.

**Fix:**
1. Neues Muster: `new state for port \d+: \w+ -> (\w+)` → Ziel-State
   (Listening/Master/Passive/Slave/Faulty, case-sensitive wie statime es
   loggt; Muster case-insensitiv unschädlich). Alte State-Muster entfernen.
2. Inferenz-Logik (Zeilen 294-299) **entfernen** – kein SLAVE aus Daten
   ableiten.
3. Bei **jedem** erkannten State-Übergang: `_pending_metrics`-Metriken
   (`offset_ns`, `freq_ppb`, `path_delay_ns`) auf `{}` leeren und
   `_last_state` setzen. Dadurch verschwinden alte Werte sofort beim
   Verlassen von SLAVE; beim Betreten von SLAVE füllen sie sich mit der
   nächsten Estimated-Zeile.
4. Severity künftig aus dem **Level-Präfix** der Zeile
   (`ERROR`→ERROR, `WARN`→WARNING, sonst INFO); Message-Muster `error`/
   `warn`/`timeout`/`sync_lost` entfallen als Severity-Quelle (False
   Positives wie „ParseError" in Message-Texten verschwinden; Zähler
   `errors`/`warnings` zählen dann nur noch echte Level).

### C – Metrik-Extraktion (log_parser.py + Schwellenstellen)

1. **offset:** `round(float(...))` statt `abs(int(float(...)))` –
   Vorzeichen bleibt erhalten, korrektes Runden (log_parser.py:178).
2. **freq:** Log-Wert ist ppm → `round(float * 1000)` als `freq_ppb`
   (1,234 ppm → 1234 ppb). Aktuell dauerhaft „Freq: 1 ppb".
3. **path_delay:** `round(float(...))` (4567,8 → 4568); Muster präzisieren
   zu `delay (-?[\d.]+)\+-` (kein `ns`-Suffix im echten Format).
4. **Summary:** `is not None` statt `or` (Offset 0 darf nicht auf Pending
   zurückfallen, log_parser.py:263-266); `path_delay` bekommt denselben
   Pending-Fallback wie offset/freq (Zeile 250).
5. **Toter Ballast:** ungenutzte Muster (`offset\s*[=:]`, `Estimated
   offset … ns`-Variante ohne `+-`, `rms`, `port_state`) entfernen bzw.
   durch die präzisen ersetzen.
6. **Vorzeichen an Schwellen:** Vergleiche nutzen künftig `abs()`:
   - `lock_gate.py` `feed()`: `abs(offset_ns) <= threshold_ns`
   - Icon-Handler `main_window.py` `_on_sync_status`: `abs(ptp_offset) <= 200`
   - Buckets in `_update_sync_light`/„Locked"-Logik (control_tab.py):
     Vergleich mit `abs(offset)`, Anzeige im Bucket-Label als Magnitude
     (`Locked (123 ns)`), **Offset-Label zeigt das Vorzeichen** (`-123 ns`).
7. **Verbose-Logtext ehrlich** (control_tab.py:955-959): Meldungen
   beschreiben künftig Summary-Rate (10 bzw. 1 Zeile/s), nicht „all lines".

### Rohlog-Checkbox (control_tab.py)

- Neue `QCheckBox("Filtered")` direkt neben `verbose_cb`
  (`log_header`), **Default: an** (aktueller Zustand). Kein QSettings-
  Persistenz (entspricht Verbose).
- **Aus** = Rohmodus: jede vollständige Zeile **unverändert** anzeigen
  (keine Kürzung auf 200 Zeichen, keine Summary), weiterhin nach Level
  färben (nur Kosmetik, Inhalt unberührt), `_trim_terminal` greift wie
  bisher (Flut-Schutz).
- **Parser läuft in beiden Modi weiter** (Seiteneffekte von `parse_line`
  – Metriken, Zähler – bleiben aktiv, Status-Panel/LockGate/Icons sind
  unberührt); im Rohmodus wird das Retournat einfach nicht angezeigt.
- Verbose bleibt unabhängig und wirkt nur im gefilterten Modus
  (Summary-Intervall 1,0 s ↔ 0,1 s); im Rohmodus ohne Effekt.
- Umschalten wirkt ab dem nächsten 50-ms-Flush.

## Approaches (Design-Entscheidungen)

| Ansatz | Trade-off | Entscheidung |
|---|---|---|
| **1. Parser an echte Formate angleichen + Puffer-Fix + Raw-Checkbox** (diese Spec) | GUI-seitig, klein, TDD-fähig; weiterhin Regex-abhängig vom statime-Format | **vom User gewählt** |
| 2. statime-Logformat ändern (Rust) | sauberste Quelle, aber separates Repo/Binary, Versionierung, Neubuild | verworfen |
| 3. Metriken via metrics-/usrvclock-Socket statt Log-Parsing | robuster gegen Format-Drift, aber Prozess-Lebenszyklus + Client-Logik nötig | verworfen (künftige Option) |

## Non-goals

- Metrik-Timeout/Ablaufüberwachung (Paket D) – ausdrücklich nicht gewünscht.
- Änderungen an statime, PipeWire- oder LockGate-Grundlogik.
- Persistenz der Checkboxen, Rohmodus-Filterung/Regex im Rohmodus.

## Tests (TDD, neue Datei `tests/test_log_parser.py` + Ergänzungen)

1. Estimated-Zeile (Referenzformat oben) → `offset_ns == -123` (signiert,
   gerundet), `freq_ppb == 1234`, `path_delay_ns == 4568`.
2. `… -> Slave` → state SLAVE, `state_changes` +1, Pending-Metriken
   geleert; `… -> Listening` danach → state LISTENING, Metriken `None`.
3. Inferenz entfernt: Estimated-Zeile **ohne** State-Zeile setzt `_last_state`
   nicht auf SLAVE (bleibt `None`/vorheriger Wert).
4. Summary: offset 0 zeigt `offset=0ns` (kein Pending-Fallback);
   `path_delay` erscheint in Folge-Summaries via Pending.
5. Severity aus Level-Präfix: `ERROR`-Zeile → ERROR-Zähler; Zeile mit
   „ParseError"-Text ohne ERROR-Präfix → INFO.
6. Split-Line: zwei `_process_log_output`-Aufrufe mit Hälften einer
   Zeile → kein Fragment-Parsing, vollständige Zeile erst nach `\n`.
7. LockGate: `feed('SLAVE', -50)` zählt (abs ≤ 200), `feed('SLAVE', -5000)`
   nicht; bestehende Tests bleiben grün.
8. Icon-Handler: `ptp_offset=-150` → grün, `-500` → schwarz/weiß.
9. Checkbox: Default an; aus → Rohzeile inkl. >200 Zeichen unverändert im
   Terminal, `get_sync_status()` aktualisiert sich trotzdem weiter;
   an → Summary-Verhalten wie bisher.

## Offenes vom Builder

- (keine – Abschnitte durch User-Entscheidungen vollständig)
