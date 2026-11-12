# Log-Parser-Korrektur + „Filtered"-Rohlog-Checkbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der gefilterte Log-View soll aus dem schnellen statime-Trace korrekte Werte (State, signierter Offset, Frequenz in ppb, path_delay) und korrekte Severity liefern; Zeilen dürfen nicht mittelspliten; eine neue Checkbox „Filtered" schaltet die Rohzeilenansicht frei.

**Architecture:** Puffer-Fix in `_flush_terminal` (Residuum bis `\n`); Parser-Muster an die belegten statime-Formate angleichen (`Estimated offset …ns+-…, freq …+-…, delay …+-…`, `new state for port N: Alt -> Neu`), Severity aus dem Level-Präfix; Metriken signiert im Parser, `abs()` nur an den Schwellenstellen (LockGate/Icon/Buckets); Rohmodus als Anzeige-Klammer um `_process_log_output`, Parser-Seiteneffekte laufen weiter.

**Tech Stack:** Python 3.12, PyQt6, pytest/pytest-qt, ruff.

**Spec:** `docs/superpowers/specs/2026-11-12-log-parser-and-raw-log-design.md`

## Global Constraints

- Direkt auf `main`, kein Worktree; TDD (RED→GREEN) pro Task.
- ruff: `pipx run ruff check . --no-cache --statistics` darf Basis 277 nicht überschreiten (aktuell 272).
- Nach jedem Task: installierte Kopie synchron — `diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui` muss leer sein (geänderte `.py` vorher mit `cp` nach `/home/jacob/audio-inferno/gui/inferno_gui/…` übertragen).
- Verifikation: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q` (venv fehlt evtl.: `python3 -m venv --system-site-packages /tmp/opencode/inferno-dev && /tmp/opencode/inferno-dev/bin/pip install pytest pytest-qt`); bestehende 39 Tests bleiben grün.
- Keine Änderungen an statime; keine echten Prozess-/pw-cli-Aufrufe in Tests.
- Locked (Verbraucher-Vertrag): `ptp_state == 'SLAVE' and ptp_offset is not None and abs(ptp_offset) <= 200`.
- State-Werte des Parsears UPPERCASE: `'SLAVE'`, `'MASTER'`, `'LISTENING'`, `'PASSIVE'`, `'FAULTY'`, `'UNCALIBRATED'` (statime loggt gemischte Schreibweise, Consumers vergleichen uppercase).
- Rohmodus: Zeilen **unverändert** (keine Kürzung auf 200 Zeichen), Färbung nach Level bleibt; `_trim_terminal` mit `_MAX_TERMINAL_LINES = 3000` greift weiterhin.
- Kein Metrik-Timeout (Paket D ausdrücklich nicht gewünscht).

## Review Focus

1. **Trace-Zeile wird mitten in der Zahl geteilt** (50-ms-Flush bei hohem Durchsatz) — vollständige Zeilen müssen verarbeitet werden, das Residuum bleibt liegen → Task 1, `test_complete_lines_processed_residue_kept` + `test_partial_line_kept_in_buffer`.
2. **Sync-Verlust bei laufendem statime** (`Slave -> Listening` ohne Prozessende) — alte Offset-/Freq-Werte müssen sofort auf None fallen, sonst LockGate/Icon/Light falsch → Task 2, `test_state_transition_clears_pending_metrics`.
3. **Negative Offsets an Schwellen** (`-5000 ns` darf nicht als Locked zählen) → Task 3, `test_large_negative_offset_does_not_lock`, `test_icon_not_green_for_large_negative_offset`, `test_sync_light_bucket_uses_magnitude`.
4. **Sub-ppm-Frequenz** (`freq 0.4` = 0,4 ppm darf nicht auf 0 ppb runden) → Task 4, `test_sub_ppm_frequency`.
5. **Rohmodus-Flut + Parser im Rohmodus** (Terminal wächst nicht unbegrenzt; Status-Panel aktualisiert sich trotzdem) → Task 5, `test_raw_mode_trims_terminal` + `test_raw_mode_keeps_parser_updating`.

---

### Task 1: Split-Line-Pufferfix

**Files:**
- Modify: `inferno_gui/ui/control_tab.py` (`_flush_terminal`, ~Zeilen 805-812)
- Test: `tests/test_log_output_split.py` (neu)

**Interfaces:**
- Consumes: `_process_log_output(text: str)` (unverändert), `_stdout_buffer`/`_stderr_buffer` (str), `_write_timer` (QTimer, 50 ms).
- Produces: Vertrag von `_flush_terminal()`: beide Buffer enthalten danach nur noch unvollständige Zeilen-Residuen (ohne `\n`); komplette Zeilen wurden an `_process_log_output` übergeben. Keine Signaturänderung.

- [ ] **Step 1: Fixtures + die zwei RED-Tests schreiben**

`tests/test_log_output_split.py` — Kopf wie `tests/test_sync_icons.py:11-18` (Docstring, `os`/`sys`, `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`, `sys.path.insert` Projekt-Root; dieses Pattern ist ruff-frei). `_make_tab` **in den Testfunktionen** importieren (Stil der bestehenden Dateien): `from test_lock_gate_wiring import _make_tab` — der Import läuft mit den QSettings-/QApplication-Seiteneffekten des Wiring-Moduls mit. Dann:

```python
def test_partial_line_kept_in_buffer(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    partial = "2026-11-12T00:00:00.000000Z ERROR a: partial"
    ct._stdout_buffer = partial
    ct._flush_terminal()
    assert partial not in ct.terminal_output.toPlainText()
    assert ct._stdout_buffer == partial
    assert not ct._write_timer.isActive()

def test_complete_lines_processed_residue_kept(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    ct._stdout_buffer = (
        "2026-11-12T00:00:00.000000Z ERROR a: boom\n"
        "2026-11-12T00:00:01.000000Z ERROR b: part"
    )
    ct._flush_terminal()
    text = ct.terminal_output.toPlainText()
    assert "boom" in text                       # komplette Zeile verarbeitet
    assert "part" not in text                   # Fragment NICHT als eigene Zeile
    assert ct._stdout_buffer == "2026-11-12T00:00:01.000000Z ERROR b: part"

def test_residue_completes_on_next_flush(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    ct._stdout_buffer = "2026-11-12T00:00:00.000000Z ERROR a: par"
    ct._flush_terminal()
    ct._stdout_buffer += "tial done\n2026-11-12T00:00:02.000000Z ERROR c: next\n"
    ct._flush_terminal()
    text = ct.terminal_output.toPlainText()
    assert "partial done" in text               # über Flusses hinweg zusammengesetzt
    assert "next" in text
    assert ct._stdout_buffer == ""

def test_forced_flush_over_8kb_without_newline(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    ct._stdout_buffer = "x" * 9000              # nie `\n` → trotzdem leeren
    ct._flush_terminal()
    assert ct._stdout_buffer == ""
```

- [ ] **Step 2: RED verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_log_output_split.py -q`
Expected: FAIL — der aktuelle Code verarbeitet den ganzen Puffer und leert ihn (Residuum-Assertions schlagen fehl).

- [ ] **Step 3: `_flush_terminal` reparieren**

In `control_tab.py`: pro Buffer mit `rfind('\n')` nur das Chunk bis einschließlich letzten `\n` an `_process_log_output` übergeben, Residuum im Buffer behalten; ohne `\n`: nur bei `len > 8192` forciert verarbeiten und leeren (Modul-Konstante `_MAX_RESIDUE = 8192` neben `_MAX_TERMINAL_LINES`). Reihenfolge stdout→stderr wie bisher; `_write_timer.stop()` am Ende wie bisher. (Verhalten vollständig durch die vier Tests determiniert; kein Code-Body nötig.)

- [ ] **Step 4: GREEN verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle Tests grün (neue 4 + bestehende 39).

- [ ] **Step 5: Commit + Sync**

```bash
git add inferno_gui/ui/control_tab.py tests/test_log_output_split.py
git commit -m "fix: keep incomplete log line residue across 50ms flushes"
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py
diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui   # leer
```

---

### Task 2: State-Patterns + Severity aus Level-Präfix

**Files:**
- Modify: `inferno_gui/core/log_parser.py` (`STATIME_PATTERNS`, `parse_line`, `update_pending_metrics`)
- Test: `tests/test_log_parser.py` (neu)

**Interfaces:**
- Consumes: `StatimeLogParser.parse_line(line) -> ParsedLogEntry | None`, `get_sync_status() -> dict` mit Keys `state`/`offset_ns`/`freq_ppb`/`path_delay_ns`/`errors`/`warnings`.
- Produces: `entry.state: Optional[str]` **uppercase** (`'SLAVE'` etc.) genau bei erkannten Übergängen; bei jedem Übergang sind `offset_ns`/`freq_ppb`/`path_delay_ns` in `get_sync_status()` danach `None`; Severity = Level-Präfix (`ERROR`→ERROR, `WARN`→WARNING, sonst INFO); Inferenz-SLAVE existiert nicht mehr. `state_changes`-Counter zählt echte Übergänge.

- [ ] **Step 1: Fixtures + RED-Tests in neuer Datei `tests/test_log_parser.py`**

Reines Python, kein Qt — nur `sys.path.insert(0, …)` wie `tests/test_layout_smoke.py:9-10`. Fixtures:

```python
EST = ("2026-11-12T14:33:21.123456Z  TRACE statime::filters::kalman: "
       "Estimated offset -123.45ns+-12.3ns, freq 1.234+-0.567, delay 4567.8+-12.3")
TRANS_SLAVE = ("2026-11-12T14:33:22.123456Z  INFO statime::port: "
               "new state for port 0: Listening -> Slave")
TRANS_LISTEN = ("2026-11-12T14:33:30.123456Z  INFO statime::port: "
                "new state for port 0: Slave -> Listening")
```

```python
def test_state_transition_parsed_uppercase():
    p = StatimeLogParser()
    e = p.parse_line(TRANS_SLAVE)
    assert e is not None and e.state == 'SLAVE'
    assert p.get_sync_status()['state'] == 'SLAVE'
    assert p._counters['state_changes'] == 1

def test_state_transition_clears_pending_metrics():
    p = StatimeLogParser()
    p.parse_line(EST)
    assert p.get_sync_status()['offset_ns'] is not None   # Fixture füllt Pending
    p.parse_line(TRANS_LISTEN)
    s = p.get_sync_status()
    assert s['state'] == 'LISTENING'
    assert s['offset_ns'] is None and s['freq_ppb'] is None and s['path_delay_ns'] is None

def test_no_state_inference_from_metrics():
    p = StatimeLogParser()
    p.parse_line(EST)
    assert p.get_sync_status()['state'] == 'UNKNOWN'      # keine SLAVE-Erfindung

def test_severity_from_level_prefix():
    p = StatimeLogParser()
    e = p.parse_line("2026-11-12T14:33:21.123456Z ERROR statime::clock: Could not adjust clock frequency")
    assert e.severity == LogSeverity.ERROR
    assert p._counters['errors'] == 1
    e2 = p.parse_line("2026-11-12T14:33:21.123456Z  WARN statime::port: Duplicate sync message")
    assert e2.severity == LogSeverity.WARNING
    assert p._counters['warnings'] == 1

def test_message_text_error_word_is_not_error():
    p = StatimeLogParser()
    e = p.parse_line("2026-11-12T14:33:21.123456Z TRACE statime::socket: could not parse packet: ParseError detail")
    assert e.severity == LogSeverity.INFO
    assert p._counters['errors'] == 0
```

- [ ] **Step 2: RED verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_log_parser.py -q`
Expected: FAIL — `-> Slave` matched kein Muster (None/kein State), Inferenz setzt SLAVE, „ParseError" zählt als ERROR.

- [ ] **Step 3: State-Muster, Inferenz, Severity umstellen**

In `log_parser.py`:
1. Neues State-Muster in `STATIME_PATTERNS`: `'pattern': re.compile(r'new state for port \d+: \w+ -> (\w+)')` mit `'state'`-Zielwert; parse-Position: Gruppe(1) mit `.upper()` als `entry.state`. Alle `(?:to|entered)`-State-Muster **und** die Message-Severity-Muster (`error`, `warning`, `sync_lost`, `timeout`) entfernen — Severity wird **vor** der Musterschleife aus dem Level-Präfix bestimmt: `re.match(r'^\S+\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s', line)` → ERROR/WARNING/INFO (kein Treffer → INFO, z. B. sudo-/Config-Fehler ohne Präfix).
2. `update_pending_metrics`: Inferenz-`elif` (Zeilen 294-299) entfernen; bei gesetztem `entry.state` **zusätzlich** `offset_ns`/`freq_ppb`/`path_delay_ns` aus `_pending_metrics` löschen.
3. `errors`/`warnings`-Counter zählen nur noch die Level-Präfix-Klasse (nicht pro Muster).

- [ ] **Step 4: GREEN verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle grün (neue 5 + bestehende 43).

- [ ] **Step 5: Commit + Sync**

```bash
git add inferno_gui/core/log_parser.py tests/test_log_parser.py
git commit -m "fix: parse real statime state transitions and derive severity from level prefix"
cp inferno_gui/core/log_parser.py /home/jacob/audio-inferno/gui/inferno_gui/core/log_parser.py
diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui   # leer
```

---

### Task 3: `abs()` an allen Schwellenstellen

**Files:**
- Modify: `inferno_gui/core/lock_gate.py:12-31` (Docstring + `feed`)
- Modify: `inferno_gui/ui/main_window.py:316-320` (`_on_sync_status`)
- Modify: `inferno_gui/ui/control_tab.py` (`_update_sync_light` ~898-939, Bucket-Logik in `_update_status_panel` ~875-890)
- Test: `tests/test_lock_gate.py`, `tests/test_sync_icons.py`, `tests/test_lock_gate_wiring.py` (jeweils Ergänzung)

**Interfaces:**
- Consumes (unveränderte Signaturen): `LockGate.feed(state: str | None, offset_ns: int | None) -> bool`, `MainWindow._on_sync_status(status: dict) -> None`, `ControlTab._update_status_panel()`.
- Produces: Vergleiche nutzen `abs(offset)`; Bucket-Labels zeigen Magnitude (`Locked (150 ns)`), `ptp_offset_label` zeigt das Vorzeichen (`Offset: -5000 ns`). Reihenfolge vor Task 4, damit signierte Werte (ab Task 4) nie ungeschützt an Schwellen treffen.

- [ ] **Step 1: RED-Tests ergänzen**

`tests/test_lock_gate.py`:

```python
def test_negative_offset_counts_as_hit():
    g = LockGate(threshold_ns=200, required_ticks=2)
    assert g.feed('SLAVE', -50) is False
    assert g.feed('SLAVE', -50) is True      # abs(-50) <= 200 zählt

def test_large_negative_offset_does_not_lock():
    g = LockGate(threshold_ns=200, required_ticks=2)
    g.feed('SLAVE', -5000)
    assert g.stable_count == 0
    assert g.feed('SLAVE', -5000) is False   # alt: -5000 <= 200 → True (falsch)
```

`tests/test_sync_icons.py` — Muster der Datei (Fixture `qt_offscreen`, Patching von `setWindowIcon`/`tray_icon`) verwenden; zwei neue Tests:

```python
def test_icon_not_green_for_large_negative_offset(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    mw._on_sync_status({'ptp_running': True, 'ptp_state': 'SLAVE',
                        'ptp_offset': -500, 'ptp_freq': 0})
    # alt: -500 <= 200 → True → fälschlich grün
    assert mw._sync_icons_locked is False
    assert calls == []
    mw.hide()


def test_icon_green_for_small_negative_offset(qt_offscreen, monkeypatch):
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    mw._on_sync_status({'ptp_running': True, 'ptp_state': 'SLAVE',
                        'ptp_offset': -150, 'ptp_freq': 0})
    assert mw._sync_icons_locked is True      # abs(-150) <= 200
    assert len(calls) == 2
    mw.hide()
```

`tests/test_lock_gate_wiring.py` (get_sync_status monkeypatchen wie `test_lock_triggers_single_node_creation`, Zeile 132-134):

```python
def test_sync_light_bucket_uses_magnitude(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    monkeypatch.setattr(ct.parser, "get_sync_status",
                        lambda: {'state': 'SLAVE', 'offset_ns': -5000, 'freq_ppb': None})
    ct._update_status_panel()
    assert ct.sync_label.text() == "SLAVE (5000 ns)"          # Magnitude im Bucket
    assert ct.ptp_offset_label.text() == "Offset: -5000 ns"    # Vorzeichen im Label
    assert ct.ptp_state_label.text() == "State: SLAVE"         # nicht "Locked"

def test_sync_light_locked_bucket_with_small_negative_offset(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    monkeypatch.setattr(ct.parser, "get_sync_status",
                        lambda: {'state': 'SLAVE', 'offset_ns': -150, 'freq_ppb': None})
    ct._update_status_panel()
    assert ct.sync_label.text() == "Locked (150 ns)"
    assert ct.ptp_state_label.text() == "State: Locked"
```

- [ ] **Step 2: RED verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_lock_gate.py tests/test_sync_icons.py tests/test_lock_gate_wiring.py -q`
Expected: die neuen Negativ-Offset-Tests FAILEN (alt: `-5000 <= 200` wahr), die Magnitude-Labels FAILEN.

- [ ] **Step 3: `abs()` an den drei Stellen umsetzen**

1. `lock_gate.py` `feed`: `hit = state == 'SLAVE' and offset_ns is not None and abs(offset_ns) <= self.threshold_ns` (+ Docstring-Zeile 12-13 auf `abs(offset_ns)` anpassen).
2. `main_window.py` `_on_sync_status`: Vergleich `abs(status.get('ptp_offset')) <= 200` (None-Check bleibt vorangestellt).
3. `control_tab.py`: alle Offset-Vergleiche in `_update_sync_light` und in der Bucket-Logik von `_update_status_panel` (`<= 200`, `<= 1000`) mit `abs(offset)`; Bucket-Label-Strings `f"Locked ({abs(offset)} ns)"`, `f"Syncing... ({abs(offset)} ns)"`, `f"SLAVE ({abs(offset)} ns)"`; `ptp_offset_label` bleibt **ohne** abs (`f"Offset: {status['offset_ns']} ns"`).

- [ ] **Step 4: GREEN verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle grün (Suite wächst um 6 Tests → 54).

- [ ] **Step 5: Commit + Sync**

```bash
git add inferno_gui/core/lock_gate.py inferno_gui/ui/main_window.py inferno_gui/ui/control_tab.py tests/
git commit -m "fix: compare ptp offset magnitude at lock, icon and sync light thresholds"
cp inferno_gui/core/lock_gate.py /home/jacob/audio-inferno/gui/inferno_gui/core/lock_gate.py
cp inferno_gui/ui/main_window.py /home/jacob/audio-inferno/gui/inferno_gui/ui/main_window.py
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py
diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui   # leer
```

---

### Task 4: Metrik-Extraktion (signiert, ppm→ppb, Summary)

**Files:**
- Modify: `inferno_gui/core/log_parser.py` (`STATIME_PATTERNS`, Metrik-Extraktion in `parse_line`, `_create_summary_entry`)
- Test: `tests/test_log_parser.py` (Ergänzung; Fixtures `EST`/`TRANS_*` wiederverwenden)

**Interfaces:**
- Consumes: Fixtures und `StatimeLogParser`-API aus Task 2.
- Produces: `entry.offset_ns: int | None` **signiert, gerundet**; `entry.freq_ppb: int | None` in **ppb** (`round(ppm * 1000)`); `entry.path_delay_ns: int | None` gerundet; Summary-Message-Format `state=X | offset=Yns | freq=Zppb | path_delay=Wns` mit Pending-Fallback für **alle** drei Metriken; `base or pending` durch `… if … is not None else …` ersetzt.

- [ ] **Step 1: RED-Tests ergänzen (in `tests/test_log_parser.py`)**

```python
def test_estimated_line_metrics_signed_and_converted():
    p = StatimeLogParser()
    e = p.parse_line(EST)
    assert e.offset_ns == -123        # signiert + gerundet (alt: 123 via abs/int)
    assert e.freq_ppb == 1234         # 1.234 ppm → 1234 ppb (alt: 1)
    assert e.path_delay_ns == 4568    # round(4567.8) (alt: 4567)

def test_sub_ppm_frequency():
    p = StatimeLogParser()
    e = p.parse_line(EST.replace("freq 1.234", "freq 0.4"))
    assert e.freq_ppb == 400          # 0.4 ppm → 400 ppb (alt: 0)

def test_summary_message_includes_all_pending_metrics():
    p = StatimeLogParser(filter_interval=0.0)
    p.parse_line(EST)                 # Pending füllen
    e = p.parse_line("2026-11-12T14:33:25.123456Z  INFO statime::port: plain info line")
    assert e is not None
    assert "offset=-123ns" in e.message
    assert "freq=1234ppb" in e.message
    assert "path_delay=4568ns" in e.message   # alt: kein Pending-Fallback → fehlt

def test_summary_entry_keeps_zero_offset():
    p = StatimeLogParser(filter_interval=0.0)
    p.parse_line(EST)                                  # Pending -123
    zero = EST.replace("offset -123.45", "offset 0")
    e = p.parse_line(zero)
    assert e.offset_ns == 0                            # alt: `0 or pending` → -123
```

Hinweis: `filter_interval=0.0` macht die Summary-Auslösung deterministisch (INTervall-Bedingung `>= 0` immer wahr).

- [ ] **Step 2: RED verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_log_parser.py -q`
Expected: die 4 neuen Tests FAILEN, die 5 aus Task 2 bleiben grün.

- [ ] **Step 3: Metrik-Muster und Summary reparieren**

In `log_parser.py`:
1. Muster präzisieren/ersetzen (echtes Format, **kein** `ns`-Suffix bei `delay`, `freq` ohne Einheit):
   - offset: `re.compile(r'Estimated offset (-?[\d.]+)ns\+-')` (Key `offset`) — die alten Muster `offset\s*[=:]…` und `Estimated\s+offset\s+…\s*ns` (ohne `+-`) entfernen;
   - freq: `re.compile(r'freq (-?[\d.]+)\+-')` (Key `freq_ppb`);
   - delay: `re.compile(r'delay (-?[\d.]+)\+-')` (Key `path_delay`) — altes `path_delay\s+(\d+)` und `delay\s+…` entfernen;
   - tote Muster `rms` und `port_state` entfernen.
2. Extraktion in `parse_line`: offset `round(float(g1))` **ohne abs**; freq `round(float(g1) * 1000)`; path_delay `round(float(g1))`.
3. `_create_summary_entry`: Message-Teile bekommen denselben Pending-Fallback (`base is not None else pending`) für path_delay (Zeile 250) wie für offset/freq; zurückgegebene Felder `offset_ns`/`freq_ppb`/`path_delay_ns` per `if … is not None else …` statt `or` (Zeilen 263-266).

- [ ] **Step 4: GREEN + Regression**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle grün (Suite 58).

- [ ] **Step 5: Commit + Sync**

```bash
git add inferno_gui/core/log_parser.py tests/test_log_parser.py
git commit -m "fix: extract signed offset, ppm-to-ppb freq and delay from real statime format"
cp inferno_gui/core/log_parser.py /home/jacob/audio-inferno/gui/inferno_gui/core/log_parser.py
diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui   # leer
```

---

### Task 5: „Filtered"-Checkbox (Rohmodus) + ehrlicher Verbose-Text

**Files:**
- Modify: `inferno_gui/ui/control_tab.py` (Log-Header ~304-309, `_process_log_output` ~814-823, `_on_verbose_toggled` ~955-959)
- Test: `tests/test_raw_log_checkbox.py` (neu)

**Interfaces:**
- Consumes: `parser.parse_line(line)` (Seiteneffekte: Metriken/Zähler — laufen in beiden Modi), `_append_colored(text: str, severity: LogSeverity)`, `format_log_entry(entry)`, `_MAX_TERMINAL_LINES = 3000`.
- Produces: `ControlTab.filtered_cb: QCheckBox` (Text `"Filtered"`, Default `setChecked(True)`, ohne QSettings-Persistenz).
- Test-Fixtures: `from test_lock_gate_wiring import _make_tab` und `from test_log_parser import EST` — **in den Testfunktionen** importieren (pytest-Prepend-Modus macht Geschwister-Module importierbar; beide Module erledigen sys.path/QSettings/QApplication beim Import).

- [ ] **Step 1: RED-Tests in neuer Datei `tests/test_raw_log_checkbox.py`**

Kopf wie `tests/test_sync_icons.py:11-18` (Docstring, `os`/`sys`, `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`, `sys.path.insert` Projekt-Root). Dann:

```python
def test_filtered_checkbox_defaults_checked(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    assert ct.filtered_cb.text() == "Filtered"
    assert ct.filtered_cb.isChecked() is True


PLAIN = "2026-11-12T14:33:21.123456Z  TRACE statime::port: some raw trace detail"


def test_raw_mode_shows_plain_lines_verbatim(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    ct._process_log_output(PLAIN + "\n")
    assert PLAIN in ct.terminal_output.toPlainText()


def test_raw_mode_does_not_truncate_long_lines(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    long_line = "2026-11-12T14:33:21.123456Z TRACE a: " + "x" * 400
    ct._process_log_output(long_line + "\n")
    assert long_line in ct.terminal_output.toPlainText()   # alle 400 x


def test_filtered_mode_hides_plain_lines(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._process_log_output(PLAIN + "\n")
    assert PLAIN not in ct.terminal_output.toPlainText()


def test_raw_mode_keeps_parser_updating(monkeypatch):
    from test_lock_gate_wiring import _make_tab
    from test_log_parser import EST

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    ct._process_log_output(EST + "\n")
    assert ct.parser.get_sync_status()['offset_ns'] is not None


def test_raw_mode_trims_terminal(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    for i in range(3500):
        ct._process_log_output(f"raw line {i}\n")
    assert ct.terminal_output.document().blockCount() <= 3000   # _MAX_TERMINAL_LINES
```

- [ ] **Step 2: RED verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_raw_log_checkbox.py -q`
Expected: FAIL — `filtered_cb` existiert noch nicht (`AttributeError`), Rohzeilen werden nicht angezeigt.

- [ ] **Step 3: Checkbox + Rohmodus + Verbose-Text**

In `control_tab.py`:
1. Log-Header (neben `verbose_cb`, Zeile ~309): `self.filtered_cb = QCheckBox("Filtered")`, `self.filtered_cb.setStyleSheet("font-size: 11px;")`, `setChecked(True)`, `log_header.addWidget(self.filtered_cb)`.
2. `_process_log_output`: Rohmodus-Vorzeile `raw = not self.filtered_cb.isChecked()`; pro Zeile **immer** `entry = self.parser.parse_line(line)`; dann: `raw` → `self._append_colored(line, entry.severity if entry else LogSeverity.INFO)` (Zeile unverändert, keine `[:200]`-Kürzung — die gilt nur in `entry.message` der gefilterten Anzeige); gefiltert → wie bisher `if entry: _append_colored(format_log_entry(entry), entry.severity)`.
3. `_on_verbose_toggled`-Texte ehrlich: `"Verbose mode enabled - showing summaries 10x/sec"` / `"Verbose mode disabled - filtered output (1 line/sec)"`.

- [ ] **Step 4: GREEN verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle grün (Suite 64).

- [ ] **Step 5: Commit + Sync**

```bash
git add inferno_gui/ui/control_tab.py tests/test_raw_log_checkbox.py
git commit -m "feat: add Filtered checkbox to show raw statime trace output"
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py
diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui   # leer
```
