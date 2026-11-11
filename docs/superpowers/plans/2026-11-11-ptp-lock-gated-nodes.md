# PTP-Lock-Gated PipeWire-Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PipeWire-Nodes werden erst erzeugt, nachdem der PTP-Sync über 5 aufeinanderfolgende Status-Ticks stabil unter der Versions-Schwelle (v2: 1000 ns, v1: 1500 ns) liegt – plus Fix der defekten Node-Args (`86d36dd`-Regression) und ehrlichem Erfolgs-Logging.

**Architecture:** Neue pure Klasse `LockGate` in `core/lock_gate.py` (zählt stabile Treffer-Ticks, einmaliges Lock-Ergebnis). `ControlTab.start_ptp` erzeugt die Nodes nicht mehr direkt, sondern setzt eine Warteflag; `_update_status_panel` (500-ms-Tick) füttert den Gate und erzeugt die Nodes beim Lock. Gleichzeitig werden `sink_cmd`/`source_cmd` von literalen `'{`/`'}`-Tokens auf schlichte `key=value`-Args bereinigt und der Erfolg per Exit-Code + `pw-cli ls Node` verifiziert.

**Tech Stack:** Python 3.12, PyQt6 (QProcess/QTimer), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-11-ptp-lock-gated-nodes-design.md`

## Global Constraints

- Verifikation: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
- ruff-Parität: Rule-Histogramm gegen Basis `9dd1c97` (keine neuen Regeln/Verstöße)
- Installierte Kopie nach jedem Fix synchron halten: `cp -r inferno_gui /home/jacob/audio-inferno/gui/` + `diff -q` je Datei
- Direkt auf `main`, kein Worktree; TDD (RED → GREEN); Commit nach jedem Task
- QSettings in Tests auf Temp-Verzeichnis umleiten (Modul-Muster aus `tests/test_layout_smoke.py` übernehmen) – echte User-Settings nie anfassen
- Keine echten `pw-cli`-/`sudo`-/`statime`-Aufrufe in Tests (immer mocken)
- Anzeige-Logik (≤200 ns „Locked"-Label, ≤1000 ns „Syncing…") bleibt unverändert – Gate und Display sind getrennt
- Schwellwerte exakt: **PTPv2 = 1000 ns, PTPv1 = 1500 ns, Stabilität = 5 Ticks, kein Timeout**

## Review Focus

Jede Zeile gehört zum Task, dessen Tests sie festnageln:

1. **Doppelte Node-Erzeugung** (Lock-Tick feuert, Flag bleibt gesetzt, nächster Tick erzeugt nochmal) → Test in Task 2: nach Lock kein zweiter `_create_pipewire_nodes`-Aufruf.
2. **PTP-Exit vor Lock** (Flag bleibt hängen, Nodes werden beim nächsten Start verwaist) → Test in Task 2: `_ptp_finished` vor Lock setzt Flag zurück und loggt „no PipeWire nodes created".
3. **Offset None trotz SLAVE** (Parser kennt State, aber noch keinen Messwert) → Test in Task 1: `feed('SLAVE', None)` zählt nicht als Treffer.
4. **Falscher Schwellwert je Radio-Position** (v1- statt v2-Schwelle) → Test in Task 2: `start_ptp` baut Gate mit 1500 bei `ptp_v1_radio` geprüft, 1000 bei v2.
5. **Stop während der Wartephase** (Flag/Aufruf-Zähler bleiben, Nodes werden später unerwartet erzeugt) → Test in Task 2: `stop_ptp` vor Lock → kein Node-Aufruf, Flag weg.
6. **Node-Args-Regression** (`'{`/`'}`-Tokens kommen zurück) → Test in Task 3.
7. **„created successfully" trotz Fehler** (Exit-Code/Verifikation ungeprüft) → Test in Task 4.

---

### Task 1: `LockGate` – pure Lock-Logik

**Files:**
- Create: `inferno_gui/core/lock_gate.py`
- Test: `tests/test_lock_gate.py`

**Interfaces:**
- Produces: `class LockGate` mit `__init__(self, threshold_ns: int, required_ticks: int)` (beide als öffentliche Attribute `self.threshold_ns`, `self.required_ticks` gespeichert), `feed(self, state: str | None, offset_ns: int | None) -> bool` (True genau einmal, wenn `required_ticks` Treffer in Folge erreicht sind; danach liefert `feed` weiter True, bis `reset()`), `reset(self) -> None`, Eigenschaft `stable_count: int`. Treffer = `state == 'SLAVE'` und `offset_ns is not None` und `offset_ns <= threshold_ns`; jeder Nicht-Treffer setzt `stable_count` auf 0.

- [ ] **Step 1: Schreib den fehlgeschlagenden Test**

```python
# tests/test_lock_gate.py
from inferno_gui.core.lock_gate import LockGate

def test_lock_after_five_stable_ticks():
    g = LockGate(threshold_ns=1000, required_ticks=5)
    for _ in range(4):
        assert g.feed('SLAVE', 500) is False
    assert g.feed('SLAVE', 500) is True
    assert g.stable_count == 5

def test_interrupt_resets_counter():
    g = LockGate(1000, 5)
    for _ in range(3):
        g.feed('SLAVE', 500)
    assert g.feed('LISTENING', None) is False      # State-Wechsel
    assert g.stable_count == 0
    for _ in range(4):
        assert g.feed('SLAVE', 999) is False
    assert g.feed('SLAVE', 999) is True

def test_offset_none_is_no_hit():
    g = LockGate(1000, 5)
    assert g.feed('SLAVE', None) is False
    assert g.stable_count == 0

def test_offset_above_threshold_is_no_hit():
    g = LockGate(1000, 5)
    assert g.feed('SLAVE', 1001) is False
    assert g.stable_count == 0

def test_threshold_is_inclusive():
    g = LockGate(1000, 1)
    assert g.feed('SLAVE', 1000) is True

def test_reset_clears_state():
    g = LockGate(1000, 5)
    for _ in range(5):
        g.feed('SLAVE', 100)
    g.reset()
    assert g.stable_count == 0
    assert g.feed('SLAVE', 100) is False
```

- [ ] **Step 2: Test laufen lassen, Fehler verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_lock_gate.py -q`
Expected: FAIL (ImportError: cannot import name 'LockGate')

- [ ] **Step 3: `LockGate` implementieren**

In `inferno_gui/core/lock_gate.py`: Klasse wie in „Interfaces" oben. `feed` prüft Trefferbedingung, inkrementiert bzw. setzt zurück, gibt `stable_count >= required_ticks` zurück; solange schon erreicht (`self._locked` intern), liefert `feed` ohne Rückschlag weiter True.

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_lock_gate.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add inferno_gui/core/lock_gate.py tests/test_lock_gate.py
git commit -m "feat: add LockGate pure lock-detection logic"
```

---

### Task 2: Gate-Verdrahtung in `ControlTab`

**Files:**
- Modify: `inferno_gui/ui/control_tab.py` (`__init__` ~53, `start_ptp` ~421-481 mit Node-Aufruf Zeile 470, `_update_status_panel` ~734, `stop_ptp` ~508, `_ptp_finished` ~663, `_reset_ptp_state` ~642)
- Test: `tests/test_lock_gate_wiring.py`

**Interfaces:**
- Consumes: `LockGate(threshold_ns, required_ticks)` aus Task 1.
- Produces: Instanz-Attribute `self._lock_gate: LockGate | None` und `self._awaiting_lock: bool` (initial False in `__init__`); Log-Strings exakt: `"Waiting for PTP lock before creating PipeWire nodes... (threshold {n} ns)"`, `"PTP locked (offset {o} ns, 5/5 ticks) - creating PipeWire nodes..."`, `"PTP exited before lock - no PipeWire nodes created"`, `"still waiting for lock: state={s}, offset={o} ns"` (letztere alle 20 Ticks = 10 s).

- [ ] **Step 1: Schreib die fehlgeschlagenen Wiring-Tests**

`tests/test_lock_gate_wiring.py` – Muster wie `test_layout_smoke.py` (QSettings auf Temp, `QApplication.instance()`):

```python
def _make_tab(monkeypatch):
    # QProcess, get_statime_binary, get_default_statime_config mocken:
    # - FakeQProcess: waitForFinished->True, exitCode->0, state()->Running, start() ok
    # - statime_bin = Path("/bin/sh") (exists), config -> tempfile-Path
    # - interface_combo: addItem("eth0", "eth0"), setCurrentIndex(0)
    ...

def test_start_ptp_does_not_create_nodes_immediately(monkeypatch):
    ct, created = _make_tab(monkeypatch)
    ct.start_ptp()
    assert created == [], "nodes must not be created before lock"
    assert ct._awaiting_lock is True
    assert ct._lock_gate.threshold_ns == 1000   # v2 Standard

def test_v1_radio_uses_1500_ns(monkeypatch):
    ct, _ = _make_tab(monkeypatch)
    ct.ptp_v1_radio.setChecked(True)
    ct.start_ptp()
    assert ct._lock_gate.threshold_ns == 1500

def test_lock_triggers_single_node_creation(monkeypatch):
    # _awaiting_lock=True, _lock_gate=LockGate(1000,5), is_ptp_running=True,
    # parser.get_sync_status gemockt auf {'state':'SLAVE','offset_ns':500,...}
    # 5x _update_status_panel() -> genau 1 Aufruf, danach Flag False,
    # 5 weitere Aufrufe -> weiterhin 1 Aufruf
    ...

def test_no_lock_keeps_waiting_and_logs(monkeypatch):
    # state LISTENING -> 10 Aufrufe: 0 Node-Aufrufe, Flag bleibt True,
    # ab 20. Tick „still waiting for lock" im Log
    ...

def test_stop_during_wait_clears_flag(monkeypatch):
    # start_ptp (gemockt) -> stop_ptp() -> Flag False, 0 Node-Aufrufe
    ...

def test_ptp_exit_before_lock_clears_flag(monkeypatch):
    # start_ptp -> _ptp_finished(1, …) -> Flag False,
    # Log enthält "PTP exited before lock - no PipeWire nodes created"
    ...
```

`_create_pipewire_nodes` in allen Tests durch einen Zähler ersetzen (`monkeypatch.setattr(ct, "_create_pipewire_nodes", recorder)`), echte `pw-cli`-Aufrufe nie zulassen.

- [ ] **Step 2: Tests laufen lassen, Fehler verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_lock_gate_wiring.py -q`
Expected: FAIL (Attribute `_awaiting_lock` existiert nicht / Nodes werden sofort erzeugt)

- [ ] **Step 3: Implementierung**

- `__init__`: `self._lock_gate = None`, `self._awaiting_lock = False`.
- `start_ptp` (Zeile 470): `self._create_pipewire_nodes()` ersetzen durch
  `threshold = 1500 if self.ptp_v1_radio.isChecked() else 1000`,
  `self._lock_gate = LockGate(threshold, 5)`, `self._awaiting_lock = True`,
  `self._append_log(f"Waiting for PTP lock before creating PipeWire nodes... (threshold {threshold} ns)")`.
- `_update_status_panel` (direkt nach `status = self.parser.get_sync_status()`): wenn `self._awaiting_lock and self.is_ptp_running`: `hit = self._lock_gate.feed(status['state'], status['offset_ns'])`; bei True → Flag False, Log mit `status['offset_ns']`, `_create_pipewire_nodes()`. Zähler für 10-s-Log (20 Ticks) führen und bei Ablauf `still waiting for lock: state=…, offset=… ns` loggen und Zähler zurücksetzen.
- `_reset_ptp_state`: `self._awaiting_lock = False; self._lock_gate = None`.
- `_ptp_finished`: **vor** `_reset_ptp_state()` merken, ob `self._awaiting_lock` (und ob Nodes noch fehlten) → danach im `was_running`- bzw. Startup-Zweig `"PTP exited before lock - no PipeWire nodes created"` loggen (nur wenn Flag gesetzt war).
- `stop_ptp` bleibt über `_reset_ptp_state` abgedeckt (Flag wird dort zurückgesetzt).
- Import: `from inferno_gui.core.lock_gate import LockGate` (oben mit den anderen Imports).

- [ ] **Step 4: Alle Tests laufen lassen**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle passed (inkl. `test_layout_smoke.py`, `test_lock_gate.py`)

- [ ] **Step 5: Installierte Kopie synchronisieren**

```bash
cp inferno_gui/ui/control_tab.py inferno_gui/core/lock_gate.py /home/jacob/audio-inferno/gui/... # korrekte Pfade: gui/inferno_gui/{ui,core}/
diff -q inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py
```
Expected: keine Ausgabe (identisch)

- [ ] **Step 6: Commit**

```bash
git add inferno_gui/ui/control_tab.py tests/test_lock_gate_wiring.py
git commit -m "feat: gate PipeWire node creation on stable PTP lock"
```

---

### Task 3: Node-Args-Fix (`86d36dd`-Regression)

**Files:**
- Modify: `inferno_gui/ui/control_tab.py:_create_pipewire_nodes` (Zeilen 526-575)
- Test: `tests/test_node_args.py`

**Interfaces:**
- Consumes: nichts aus früheren Tasks (eigenständig, aber gleiche Funktion wie Task 4).
- Produces: `sink_cmd`/`source_cmd` als Listen aus **ausschließlich** `key=value`-Tokens, erstes Property-Arg `object.linger=1`, **keine** `'`, `{`, `}` in den Args.

- [ ] **Step 1: Schreib den fehlgeschlagenen Test**

```python
# tests/test_node_args.py
# Baut sink_cmd/source_cmd über die gemockte QProcess-Fassade nach
# (monkeypatch auf control_tab.QProcess, die die Argumente mitprotokolliert)
# und prüft die Roh-Listen:

def test_sink_and_source_args_are_plain_key_value(monkeypatch):
    cmds = _capture_node_commands(monkeypatch)   # -> [(sink_list, source_list)]
    sink, source = cmds
    for cmd in (sink, source):
        assert cmd[:3] == ["pw-cli", "create-node", "adapter"]
        props = cmd[3:]
        assert props[0] == "object.linger=1"
        for p in props:
            assert "'" not in p and "{" not in p and "}" not in p, p
            assert "=" in p, p
    assert "factory.name=api.alsa.pcm.sink" in sink
    assert "node.name=Inferno_sink" in sink
    assert "factory.name=api.alsa.pcm.source" in source
    assert "node.name=Inferno_source" in source
```

- [ ] **Step 2: Test laufen lassen, Fehler verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_node_args.py -q`
Expected: FAIL (erstes Property-Arg ist `'{object.linger=1`, enthält `'`)

- [ ] **Step 3: Args bereinigen**

In `_create_pipewire_nodes`: `'{'object.linger=1'` → `'object.linger=1'` (Zeile 533), `'{'` → entfernen (Zeile 544), analog source (Zeilen 550/561). Sonstige Args unverändert.

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_node_args.py -q`
Expected: PASS

- [ ] **Step 5: Installierte Kopie synchronisieren + Commit**

```bash
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py
git add inferno_gui/ui/control_tab.py tests/test_node_args.py
git commit -m "fix: plain key=value node args so object.linger takes effect"
```

---

### Task 4: Ehrliches Erfolgs-Logging bei Node-Erzeugung

**Files:**
- Modify: `inferno_gui/ui/control_tab.py:_create_pipewire_nodes` (Loop Zeilen 564-575)
- Test: `tests/test_node_args.py` (ergänzen)

**Interfaces:**
- Consumes: Task 3 (gültige Args).
- Produces: Nur bei bestätigter Existenz der Nodes Log `"{name} created successfully (verified)"`; sonst `"{name} creation FAILED: …"` mit Exit-Code bzw. stderr. Verifikation = ein zusätzlicher `pw-cli ls Node`-Aufruf (über `subprocess.run`, gemockt in Tests), dessen Ausgabe `node.name = "Inferno_sink"`/`"Inferno_source"` enthält; stderr des create-Aufrufs wird auf `error`-caseinsensitive gescannt.

- [ ] **Step 1: Schreib die fehlgeschlagenen Tests**

Ergänze `tests/test_node_args.py`:

```python
def test_success_logged_only_after_verification(monkeypatch):
    # Fake-Verhalten: create-Aufruf exit 0, `pw-cli ls Node` enthält beide Namen
    # -> Log enthält "Inferno sink created successfully (verified)"

def test_missing_node_logs_failure(monkeypatch):
    # `pw-cli ls Node` enthält die Namen NICHT -> Log enthält "creation FAILED"
    # und NICHT "created successfully"

def test_nonzero_exit_logs_failure(monkeypatch):
    # create-Aufruf liefert exitCode 1 + stderr -> Log enthält "creation FAILED"
    # und den stderr-Text
```

- [ ] **Step 2: Test laufen lassen, Fehler verifizieren**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_node_args.py -q`
Expected: FAIL (aktuelles Verfahren loggt „created successfully" ohne Prüfung)

- [ ] **Step 3: Implementieren**

Loop-Body in `_create_pipewire_nodes`:
1. `proc.exitCode() != 0` → FAILED-Log mit Exit-Code + stderr.
2. Danach `subprocess.run(['pw-cli', 'ls', 'Node'], capture_output=True, text=True, timeout=5)`; Ziel-Name (`Inferno_sink`/`Inferno_source`) muss als `node.name = "…"` vorkommen und stderr/Output darf kein case-insensitives `error` enthalten → „created successfully (verified)", sonst FAILED-Log (inkl. fehlender Verifikation).

- [ ] **Step 4: Alle Tests laufen lassen**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle passed

- [ ] **Step 5: Installierte Kopie synchronisieren + Commit**

```bash
cp inferno_gui/ui/control_tab.py /home/jacob/audio-inferno/gui/inferno_gui/ui/control_tab.py
git add inferno_gui/ui/control_tab.py tests/test_node_args.py
git commit -m "fix: verify node creation before logging success"
```

---

### Task 5: Finale Verifikation

**Files:**
- Keine Codeänderungen (nur Prüfung; bei Befund Rückgabe an Task 2-4).

- [ ] **Step 1: Vollständiger Testlauf**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle passed

- [ ] **Step 2: ruff-Parität**

Run: `ruff check . --statistics` und Vergleich mit Basis `9dd1c97` (`git stash`-freier Vergleich über `git show 9dd1c97`-Arborkopf oder Histogramm-Differenz)
Expected: keine neuen Verstöße/Regeln

- [ ] **Step 3: Installierte Kopie diff-synchron**

Run: `diff -rq inferno_gui /home/jacob/audio-inferno/gui/inferno_gui`
Expected: keine Unterschiede

- [ ] **Step 4: Ehrliche Node-Verifikation in der laufenden Umgebung (manuell, User-Abnahme)**

`sudo /home/jacob/audio-inferno/gui/run_gui.sh` → Start mit laufendem statime → Log zeigt „Waiting for PTP lock…" → nach Lock „PTP locked … creating" → `pw-cli ls Node` zeigt beide Nodes persistent.

- [ ] **Step 5: Finaler Review (frischer Reviewer), ggf. 1 Fix-Wave**
