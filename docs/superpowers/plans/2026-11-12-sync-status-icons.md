# Sync-Status-Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Taskleisten-/Fenster-Icon und Tray-Icon wechseln live zwischen schwarz/weiß (nicht sync) und grün (Locked), sobald der PTP-Sync die Locked-Schwelle erreicht.

**Architecture:** MainWindow abonniert das bereits vorhandene `ControlTab.status_changed(dict)`-Signal und setzt bei Zustandswechsel `QApplication.setWindowIcon()` + `QSystemTrayIcon.setIcon()` mit einmalig gecachten Icons. Keine neuen Abhängigkeiten, keine neuen Asset-Dateien (schwarz/weiß = `assets/icon.png`, grün = `assets/icon.svg`).

**Tech Stack:** PyQt6, pytest (+pytest-qt), ruff.

**Spec:** `docs/superpowers/specs/2026-11-12-sync-status-icon-design.md`

## Global Constraints

- Locked-Schwelle exakt wie das Display-Label: `ptp_state == 'SLAVE' and ptp_offset is not None and ptp_offset <= 200`.
- Zustand „nicht sync" = alle anderen Fälle (inkl. Start): Icon `assets/icon.png` (schwarz/weiß).
- Zustand „Locked": Icon `assets/icon.svg` (grün).
- Beide Icons wechseln: `QApplication.instance().setWindowIcon(...)` UND `self.tray_icon.setIcon(...)`.
- Swap NUR bei tatsächlichem Zustandswechsel (Merker `self._sync_icons_locked`), nicht im Timer-Takt.
- Anzeige-Logik im Control-Tab (`_update_sync_light`, Labels) bleibt unverändert.
- Verifikation: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q` (venv ggf. rekonstruieren: `python3 -m venv --system-site-packages /tmp/opencode/inferno-dev && /tmp/opencode/inferno-dev/bin/pip install pytest pytest-qt`).
- ruff-Gesamtzahl darf die Basis (277) nicht überschreiten; geänderte Dateien ohne neue Verstöße.
- Installierte Kopie nach jedem Commit synchron: `cp` der geänderten `.py` nach `/home/jacob/audio-inferno/gui/inferno_gui/…` + `diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui`.
- Testdateien: Projekt-Root in `sys.path` (Muster `tests/test_layout_smoke.py:9-10`), QSettings auf Temp, keine echten Prozess-Aufrufe.
- Arbeitsverzeichnis: `/home/jacob/codingProjekts/inferno-gui`, direkt auf `main`, kein Worktree.

## Review Focus

- **Signal-Payload-Keys:** `status_changed` liefert `ptp_state`/`ptp_offset` (NICHT `state`/`offset_ns`) – vertippt man die Keys, schweigt der Handler still (Test: `test_icon_swaps_on_locked_status` mit exakten Keys).
- **Grenzwert 200/201 ns:** 200 ns muss grün, 201 ns schwarz/weiß sein (Grenzwert-Test).
- **`offset None` / nicht-SLAVE:** weder `None`-Offset noch `MASTER`/`FAULTY` dürfen grün zeigen (Test: `test_icon_not_green_without_full_lock_condition`).
- **Doppelter Swap bei gleichem Zustand:** gleicher Zustand zweimal signalisieren darf kein `setWindowIcon`-Call auslösen (Test: `test_no_icon_swap_when_state_unchanged`).
- **Tray und Fenster wechseln zusammen:** ein Test prüft beide Aufrufe (Test: `test_icon_swaps_on_locked_status`).

---

### Task 1: Sync-Status-Icons in MainWindow verdrahten

**Files:**
- Modify: `inferno_gui/ui/main_window.py` (`__init__` ~Zeile 33-52, `_setup_tray` ~Zeile 85-141, `_connect_signals` ~Zeile 187-197, neuer Handler am Klassenende)
- Test: `tests/test_sync_icons.py` (neu)

**Interfaces:**
- Consumes: `ControlTab.status_changed: pyqtSignal(dict)` mit Payload `{'ptp_running': bool, 'ptp_state': str|None, 'ptp_offset': int|None, 'ptp_freq': int|None}` (existiert bereits, `control_tab.py:48` und `:941-948`); Assets `inferno_gui/assets/icon.png` + `icon.svg` (existieren bereits).
- Produces: `MainWindow._on_sync_status(status: dict) -> None` – Handler, der bei Zustandswechsel beide Icons setzt; Attribut `MainWindow._sync_icons_locked: bool` (Merker, Start `False`).

- [ ] **Step 1: Schreib den fehlgeschlagenden Test**

Neu in `tests/test_sync_icons.py`, folgendes Muster (sys.path-Preamble wie `tests/test_layout_smoke.py:9-10`, QSettings auf Temp, `QApplication` modulglobal halten – Muster `tests/test_lock_gate_wiring.py`):

```python
def test_icon_swaps_on_locked_status(qt_offscreen, monkeypatch):
    mw = MainWindow()
    calls = []
    monkeypatch.setattr(QApplication.instance(), "setWindowIcon",
                        lambda icon: calls.append(("window", icon.cacheKey())))
    monkeypatch.setattr(mw.tray_icon, "setIcon",
                        lambda icon: calls.append(("tray", icon.cacheKey())))
    # Start: schwarz/weiß
    assert mw._sync_icons_locked is False
    mw._on_sync_status({'ptp_running': True, 'ptp_state': 'SLAVE',
                        'ptp_offset': 200, 'ptp_freq': 0})
    assert mw._sync_icons_locked is True
    assert len(calls) == 2 and {c[0] for c in calls} == {"window", "tray"}
    # beide Icons sind grün (identisch zum Cached-Icon)
    assert calls[0][1] == mw._icon_locked.cacheKey()
```

Weitere Tests in derselben Datei:
- `test_no_icon_swap_when_state_unchanged`: `_on_sync_status` zweimal mit identischem Locked-Payload → `setWindowIcon`-Aufruf-Zähler bleibt bei 0 (Merker verhindert Swap).
- `test_icon_not_green_without_full_lock_condition`: Parameterized über Payloads, die alle `False` ergeben und **keinen** Auflösungs-Call auslösen: `('SLAVE', 201)`, `('MASTER', None)`, `('FAULTY', 50)`, `(None, None)`, `('SLAVE', None)` – danach `mw._sync_icons_locked is False`.
- `test_start_icon_is_black_and_white`: nach `MainWindow()`-Init ist `mw._sync_icons_locked is False` und das initial gesetzte Icon ist `icon.png` (Merker + gecachtes `_icon_not_sync` existieren).

- [ ] **Step 2: Lauf den Test und verifiziere das FAILURE**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_sync_icons.py -v`
Expected: FAIL (`AttributeError: '_sync_icons_locked'` bzw. `_on_sync_status` existiert nicht)

- [ ] **Step 3: Implementiere den Handler in `inferno_gui/ui/main_window.py`**

- In `__init__` (nach `self._inferno_running = False`, Zeile 34): Icons einmalig cachen und Merker initialisieren:
  `self._icon_not_sync = QIcon(str(Path(__file__).parent.parent / 'assets' / 'icon.png'))`,
  `self._icon_locked = QIcon(str(Path(__file__).parent.parent / 'assets' / 'icon.svg'))`,
  `self._sync_icons_locked = False`.
- In `_setup_tray`: Tray-Icon auf `self._icon_not_sync` setzen (ersetzt den bestehenden statischen Lade-Block, Zeilen 90-104 – `icon.png` existiert, der else-Zweck bleibt als Fallback erhalten).
- In `_connect_signals` (neue Zeile): `self.control_tab.status_changed.connect(self._on_sync_status)`.
- Neuer Handler am Klassenende:

```python
def _on_sync_status(self, status: dict):
    """Icons (Fenster + Tray) dem Sync-Zustand anpassen: grün ab Locked."""
    green = (status.get('ptp_state') == 'SLAVE'
             and status.get('ptp_offset') is not None
             and status.get('ptp_offset') <= 200)
    if green == self._sync_icons_locked:
        return
    self._sync_icons_locked = green
    icon = self._icon_locked if green else self._icon_not_sync
    app = QApplication.instance()
    if app is not None:
        app.setWindowIcon(icon)
    self.tray_icon.setIcon(icon)
```

- [ ] **Step 4: Lauf den Test und verifiziere PASS**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_sync_icons.py -v`
Expected: 4 passed

- [ ] **Step 5: Gesamtsuite + ruff**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: alle grün (31 bestehende + 4 neue)

Run: `pipx run ruff check . --statistics` → `Found N errors.` mit N ≤ 277; `tests/test_sync_icons.py` ohne Verstöße.

- [ ] **Step 6: Commit + installierte Kopie synchronisieren**

```bash
git add inferno_gui/ui/main_window.py tests/test_sync_icons.py
git commit -m "feat: swap window and tray icons on PTP lock status"
cp inferno_gui/ui/main_window.py /home/jacob/audio-inferno/gui/inferno_gui/ui/main_window.py
diff -rq --exclude=__pycache__ --exclude=*.toml inferno_gui /home/jacob/audio-inferno/gui/inferno_gui
```
Expected: diff ohne Ausgabe (nur evtl. `inferno-ptpv1.toml`-Rauschen ist ausgeschlossen).

- [ ] **Step 7: Doku committen**

Spec + Plan (falls noch ungetrackt) in eigenem Commit:
```bash
git add docs/superpowers/specs/2026-11-12-sync-status-icon-design.md docs/superpowers/plans/2026-11-12-sync-status-icons.md
git commit -m "docs: add sync status icon spec and plan"
```
