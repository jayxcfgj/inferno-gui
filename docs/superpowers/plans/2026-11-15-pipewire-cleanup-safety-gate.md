# PipeWire-Cleanup Schutzgate + Freifrebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** APT-Purge der PipeWire-Distro-Pakete darf nie Kaskaden außerhalb der PipeWire-Familien auslösen (Schutzgate), und bei erfüilter Versionsprüfung (≥ 1.4.11) bekommt der User zusätzlich eine Freifrage, ob er trotzdem die neueste Version bauen möchte.

**Architecture:** Alles in `install_inferno.sh`. (1) In `step_pipewire_cleanup()` Abschnitt 3 wird die apt-Simulation mit `LC_ALL=C` ausgeführt, ihre vollständige REMOVED-/NEW-Sektion von einem festen awk-Programm gegen die Whitelist der 6 PipeWire-Familien geprüft; nur bei sauberem Gate setzt ein Flag `purge_allowed=true` und der bestehende PURGE-Prompt darf erscheinen. (2) In `step_pipewire()` ersetzt der „already installed"-`return 0` eine `prompt_yes_no`-Freifrage (Default `n`); beide Versionszweige fallen in den bereits bestehenden gemeinsamen Cleanup+Build-Pfad.

**Tech Stack:** Bash (set -euo pipefail), apt/dpkg, awk; Python-pytest String-/Strukturtests (Stil wie vorhandene `tests/test_installer_pipewire.py`).

**Spec:** `docs/superpowers/specs/2026-11-15-pipewire-cleanup-safety-gate-design.md`

## Global Constraints

- Whitelist-Familien (exakt, identisch zur Paketerkennung): `^pipewire($|-)`, `^libpipewire-`, `^libspa-`, `^wireplumber($|-)`, `^libwireplumber-`, exakt `gstreamer1.0-pipewire`.
- Purge-Prompt-Zeile `Zum Fortfahren exakt PURGE eingeben` bleibt unverändert (existierender Test).
- In `step_pipewire_cleanup()`-Body verboten (existierende Tests): `EXECUTE`, `run_root`, `log "`, `die "`, `warn "`.
- Jede Zeile, die `ldconfig` enthält, muss `run_cmd_sudo` enthalten (existierender Test).
- `step_pipewire_cleanup() {` genau 1×, `main "$@"` genau 1× (existierende Tests).
- Version-Untergrenze `1.4.11` / `[ "$patch" -ge 11 ]` bleibt unverändert.
- Rebuild-Prompt exakter Text: `Build and install the latest PipeWire version anyway?` mit Default `"n"`.
- Gate-Skip-Meldung exakt: `Purge uebersprungen (Schutzgate)` (Substring, für Test 2).
- Tests werden mit `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q` ausgeführt (venv fehlt ggf.: `python3 -m venv --system-site-packages /tmp/opencode/inferno-dev && /tmp/opencode/inferno-dev/bin/pip install -q pytest`).
- Syntax: `bash -n install_inferno.sh`. Lint: `/home/jacob/.local/bin/uvx ruff check .` — Baseline 273 Fehler, darf nicht steigen.
- `tests/` ist gitignored → Commits mit `git add -f tests/test_installer_pipewire.py`; nie `git add -A`; untracked (AppImage, `pipewire-cleanup.sh`, `pipewire-cleanup-integration-plan.md`) bleiben unberührt.
- Antworten knapp auf Deutsch; fertige Arbeit committen und pushen.

## Review Focus

1. **Locale:** Deutsche apt-Header (`Die folgenden Pakete werden ENTFERNT:`) sind unparsebar → `LC_ALL=C` erzwungen, gepinnt von `test_cleanup_simulation_uses_c_locale`.
2. **apt-Output-Form:** REMOVED-Liste gewrappt, `*`-Marker, Kommas, Sektionen in wechselnder Reihenfolge, Unrelated-Sektionen (auto-removable/Suggested) → Parser-Test-Sample enthält alle diese Elemente (`test_cleanup_gate_parses_apt_simulation_cascade`).
3. **Fail-safe:** Ein Parse-/Auswertungsfehler darf das Gate nicht „durchschlagen" lassen (Purge wäre die unsichere Richtung) → Fallback-Assignment in der Scriptstelle, gepinnt von `test_cleanup_gate_guards_purge`.
4. **TEST_MODE:** Gate läuft read-only, kein PURGE-Prompt, Dry-Run-Purge nur bei sauberem Gate; Default `n` wird auto-gewählt → funktionale Szenarien in Task 3 (apt-get-Stub).
5. **set -e:** Simulations-Capture darf bei apt-Fehler nicht abbrechen (sonst stirbt der ganze Installer) → `if sim_out=$(...)`-Bedingung, verifiziert durch `bash -n` + Szenario „apt-get schlägt fehl" in Task 3.

---

### Task 1: Schutzgate in `step_pipewire_cleanup()`

**Files:**
- Modify: `install_inferno.sh` (`step_pipewire_cleanup()`, Abschnitt 3 „APT-Purge simulieren" und Abschnitt 5 „Distro-Pakete per APT entfernen")
- Test: `tests/test_installer_pipewire.py` (anhängen)

**Interfaces:**
- Consumes: vorhandene `PKGS`-Array-Erkennung (Abschnitt 1), `log_warn`/`log_info`, `run_cmd_sudo`, `run_as_user`, `TEST_MODE`.
- Produces: Shell-Variablen `purge_allowed` (`"true"`/`"false"`, function-lokal, gesetzt vor Abschnitt 3, ausgewertet in Abschnitt 5) und `gate_prog` (lokale Variable mit dem awk-Programm-Text; Test 1 extrahiert ihn per Regex `local gate_prog='(.*?)'`).

- [x] **Step 1: Die drei fehlschlagenden Tests schreiben**

An `tests/test_installer_pipewire.py` anhängen (Imports im Funktionskörper wie im Bestand):

```python
# ---------------------------------------------------------------------------
# Regression tests: apt purge safety gate (round 3)
# ---------------------------------------------------------------------------


def test_cleanup_gate_parses_apt_simulation_cascade():
    """Schutzgate: Parsing der LC_ALL=C apt-Simulation erkennt Kaskade ausserhalb der Familien."""
    import re
    import subprocess

    content = _content()
    m = re.search(r"local gate_prog='(.*?)'", content, re.DOTALL)
    assert m, "gate_prog missing"
    sample = """Reading package lists... Done
Building dependency tree... Done
The following packages were automatically installed and are no longer required:
  aj-snapshot cabextract fonts-liberation2
Use 'sudo apt autoremove' to remove them.
The following NEW packages will be installed:
  pulseaudio
The following packages will be REMOVED:
  blueman* cable* celluloid* cinnamon* cinnamon-dbg* gstreamer1.0-pipewire*
  gstreamer1.0-plugins-bad* hypnotix* libfluidsynth3* libmpv2*
  libpipewire-0.3-0t64* libpipewire-0.3-common* libpipewire-0.3-dev*
  libspa-0.2-modules* libwireplumber-0.4-0* mint-meta-cinnamon*
  pipewire* pipewire-alsa* pipewire-audio* pipewire-bin* pipewire-jack*
  pipewire-pulse* qpwgraph* wireplumber* xdg-desktop-portal*
  xdg-desktop-portal-gtk*
0 upgraded, 1 newly installed, 33 to remove and 8 not upgraded.
"""
    proc = subprocess.run(
        ["awk", m.group(1)], input=sample, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"awk program failed: {proc.stderr}"
    found = set(proc.stdout.split())
    must_flag = {
        "cinnamon", "cinnamon-dbg", "mint-meta-cinnamon", "blueman",
        "celluloid", "hypnotix", "xdg-desktop-portal", "xdg-desktop-portal-gtk",
        "qpwgraph", "cable", "gstreamer1.0-plugins-bad", "libmpv2",
        "libfluidsynth3", "pulseaudio",
    }
    must_pass = {
        "gstreamer1.0-pipewire", "libpipewire-0.3-0t64", "libpipewire-0.3-common",
        "libpipewire-0.3-dev", "libspa-0.2-modules", "libwireplumber-0.4-0",
        "pipewire", "pipewire-alsa", "pipewire-audio", "pipewire-bin",
        "pipewire-jack", "pipewire-pulse", "wireplumber",
    }
    assert must_flag <= found, f"not flagged: {must_flag - found}"
    assert not (must_pass & found), f"wrongly flagged: {must_pass & found}"


def test_cleanup_gate_guards_purge():
    """Gate liegt vor dem PURGE-Prompt, Purge ist an purge_allowed gebunden, Fail-safe vorhanden."""
    body = _section("step_pipewire_cleanup() {")
    assert body.index("gate_prog") < body.index("Zum Fortfahren exakt PURGE eingeben")
    assert "Purge uebersprungen (Schutzgate)" in body
    assert "Auswertung fehlgeschlagen" in body, "parse failure must fail safe (skip purge)"
    i_purge_cmd = body.index('apt-get purge --no-auto-remove -y')
    guard_zone = body[max(0, i_purge_cmd - 400) : i_purge_cmd]
    assert 'purge_allowed" = "true"' in guard_zone, "purge command not guarded"


def test_cleanup_simulation_uses_c_locale():
    """apt-Simulation mit LC_ALL=C, damit die englischen Sektionsheader stabil parsebar sind."""
    content = _content()
    assert "LC_ALL=C apt-get -s purge" in content
```

- [x] **Step 2: Tests laufen lassen — alle drei müssen FAIL**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_installer_pipewire.py -q`
Expected: FAIL mit `gate_prog missing` bzw. `Purge uebersprungen (Schutzgate)` nicht gefunden bzw. `LC_ALL=C apt-get -s purge` nicht gefunden.

- [x] **Step 3: Gate implementieren**

In `step_pipewire_cleanup()`, Abschnitt 3 (beginnt mit `log_info "APT-Purge-Simulation ...`) ersetzen durch:

```bash
    # -------------------------------------------------------------------------
    # 3. APT-Purge simulieren, Schutzgate pruefen, explizite Bestaetigung
    # -------------------------------------------------------------------------
    local purge_allowed=false
    if ((${#PKGS[@]})); then
        log_info "APT-Purge-Simulation (bitte die Liste der zu entfernenden Pakete pruefen):"
        local sim_out=""
        if sim_out=$(LC_ALL=C apt-get -s purge --no-auto-remove "${PKGS[@]}" 2>&1); then
            printf '%s\n' "$sim_out"
            local gate_prog='$0 == "The following packages will be REMOVED:" { s = "R"; next }
$0 == "The following NEW packages will be installed:" { s = "N"; next }
/^[^ ]/ { s = ""; next }
s == "R" || s == "N" {
  line = $0
  gsub(/\*/, "", line)
  gsub(/,/, " ", line)
  n = split(line, a, /[ \t]+/)
  for (i = 1; i <= n; i++) {
    pkg = a[i]
    if (pkg == "") continue
    ok = (pkg ~ /^pipewire($|-)/ || pkg ~ /^libpipewire-/ || pkg ~ /^libspa-/ || pkg ~ /^wireplumber($|-)/ || pkg ~ /^libwireplumber-/ || pkg == "gstreamer1.0-pipewire")
    if (s == "N" || !ok) print pkg
  }
}'
            local violations=""
            violations=$(printf '%s\n' "$sim_out" | awk "$gate_prog" | sort -u) \
                || violations="Auswertung fehlgeschlagen"
            if [ -n "$violations" ]; then
                log_warn "Purge uebersprungen (Schutzgate): betroffene Pakete ausserhalb der PipeWire-Familien:"
                printf '%s\n' "$violations" | sed 's/^/    /'
                log_warn "Distro-Pakete bleiben installiert (Desktop/DE haengt an diesen Paketen)."
                log_info "Der Source-Build nach /usr/local hat Vorrang (PATH/ldconfig/systemd)."
# Erratum: shipped code uses `(PATH/ld.so.cache/systemd)` — the pinned `ldconfig`→`run_cmd_sudo` constraint (existing test) outranks this sample (controller ruling).
            else
                purge_allowed=true
            fi
        else
            printf '%s\n' "$sim_out"
            log_warn "APT-Simulation fehlgeschlagen - es wird nichts entfernt."
        fi

        if [ "$purge_allowed" = "true" ] && [ "$TEST_MODE" = false ]; then
            printf '\nAPT wird die oben angezeigten Pakete/Abhaengigkeiten entfernen.\n'
            printf 'Wenn dabei Desktop-, Audio-, Bluetooth- oder andere benoetigte Pakete betroffen sind: ABBRECHEN.\n'
            local answer=""
            read -r -p "Zum Fortfahren exakt PURGE eingeben: " answer || answer=""
            if [ "$answer" != "PURGE" ]; then
                log_error "Vom Benutzer abgebrochen - es wurden noch keine Pakete entfernt (nur Backup erstellt)."
                return 1
            fi
            # Audio-Dienste des Benutzers stoppen, bevor Pakete entfernt werden
            local unit
            for unit in pipewire.service pipewire.socket \
                        pipewire-pulse.service pipewire-pulse.socket \
                        wireplumber.service pipewire-media-session.service; do
                run_as_user "systemctl --user stop \"$unit\" >/dev/null 2>&1 || true"
            done
        fi
    else
        log_info "APT-Purge uebersprungen: keine passenden Pakete installiert."
    fi
```

Abschnitt 5 ersetzen durch (Purge nur bei Gate-Freigabe):

```bash
    if [ "$purge_allowed" = "true" ]; then
        log_info "Entferne Distro-Pakete via APT..."
        run_cmd_sudo "apt-get purge --no-auto-remove -y ${PKGS[*]}"
    elif ((${#PKGS[@]})); then
        log_info "APT-Purge uebersprungen (Schutzgate: Kaskade ausserhalb der PipeWire-Familien oder Simulation fehlgeschlagen)."
    else
        log_info "Keine Distro-Pakete zu entfernen."
    fi
```

Details, die der Implementierer nicht raten darf:
- `gate_prog` ist EIN single-quoted String (mehrzeilig), darf **keine** einzelnen Anführungszeichen im Text enthalten — nur `"` (deshalb alle awk-Strings doppelt gequotet).
- Der Fallback `|| violations="Auswertung fehlgeschlagen"` muss stehen bleiben (Fail-safe: lieber skippen als purgen).
- Reihenfolge im Body muss sein: `gate_prog` < `Zum Fortfahren exakt PURGE eingeben` < `apt-get purge --no-auto-remove -y`.
- Bestehender Code außerhalb Abschnitt 3/5 (Backup, Manifest-Loop, Abschlussprüfung, Services) bleibt unverändert.

- [x] **Step 4: Syntax + Tests**

Run: `bash -n install_inferno.sh && QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_installer_pipewire.py -q`
Expected: `bash -n` OK, alle Tests PASS (inkl. der 106 Bestandstests).

- [x] **Step 5: Commit**

```bash
git add install_inferno.sh
git add -f tests/test_installer_pipewire.py
git commit -m "feat: apt purge safety gate skips cascade outside pipewire families"
```

---

### Task 2: Freifrebuild bei erfüilter Versionsprüfung

**Files:**
- Modify: `install_inferno.sh` (`step_pipewire()`, Block ab `if [ "$version_ok" = true ]; then` bis `fi` vor dem Cleanup-Aufruf)
- Test: `tests/test_installer_pipewire.py` (anhängen)

**Interfaces:**
- Consumes: `prompt_yes_no` (TEST_MODE auto-wählt Default), Bestandsvariablen `pw_version`, `install_cleanup`, den bereits bestehenden gemeinsamen Pfad (Cleanup-Aufruf → Build-Dependencies → `meson setup build`).
- Produces: keine neuen Namen; nur Kontrollfluss.

- [x] **Step 1: Fehlschlagenden Test schreiben**

```python
def test_version_ok_offers_rebuild_prompt():
    """Auch bei bestandener Versionspruefung gibt es eine Freifrage (Default n),
    die in denselben Cleanup+Build-Pfad fuehrt."""
    body = _section("step_pipewire() {")
    i_ok = body.index("already installed")
    i_prompt = body.index(
        'prompt_yes_no "Build and install the latest PipeWire version anyway?" "n"'
    )
    i_cleanup = body.index("step_pipewire_cleanup")
    i_build = body.index("meson setup build")
    assert i_ok < i_prompt < i_cleanup < i_build, (
        f"wrong order: ok={i_ok} prompt={i_prompt} cleanup={i_cleanup} build={i_build}"
    )
```

- [x] **Step 2: Test laufen lassen — muss FAIL**

Run: `QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_installer_pipewire.py::test_version_ok_offers_rebuild_prompt -q`
Expected: FAIL (`Build and install the latest PipeWire version anyway?` nicht gefunden).

- [x] **Step 3: Version-Zweig umschreiben**

In `step_pipewire()` den Block

```bash
    if [ "$version_ok" = true ]; then
        log_success "PipeWire >= 1.4.11 is already installed"
        return 0
    fi
    
    log_warn "PipeWire version is older than 1.4.11 (current: $pw_version)"
    log_info "Building PipeWire from source requires development packages and takes several minutes."
    
    if ! prompt_yes_no "Build and install latest PipeWire from source?" "y"; then
        log_info "Skipping PipeWire build. Note: inferno may not work correctly with PipeWire < 1.4.11"
        return 0
    fi
```

ersetzen durch (beide Zweige fallen in den bestehenden gemeinsamen Pfad — der darauffolgende Cleanup+Build-Code bleibt 1:1 unverändert):

```bash
    if [ "$version_ok" = true ]; then
        log_success "PipeWire >= 1.4.11 is already installed ($pw_version)"
        if ! prompt_yes_no "Build and install the latest PipeWire version anyway?" "n"; then
            log_info "Installierte Version $pw_version bleibt erhalten."
            return 0
        fi
        log_info "Rebuild gewaehlt - fahre fort mit Bereinigung und Build."
    else
        log_warn "PipeWire version is older than 1.4.11 (current: $pw_version)"
        log_info "Building PipeWire from source requires development packages and takes several minutes."
        if ! prompt_yes_no "Build and install latest PipeWire from source?" "y"; then
            log_info "Skipping PipeWire build. Note: inferno may not work correctly with PipeWire < 1.4.11"
            return 0
        fi
    fi
```

Werte, die exakt so stehen müssen: Prompt-Text `Build and install the latest PipeWire version anyway?`, Default `"n"`, Substring `already installed` im Success-Log.

- [x] **Step 4: Syntax + Tests**

Run: `bash -n install_inferno.sh && QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q`
Expected: OK + `110 passed` (106 Bestand + 4 neue).

- [x] **Step 5: Commit**

```bash
git add install_inferno.sh
git add -f tests/test_installer_pipewire.py
git commit -m "feat: offer rebuild when installed pipewire already meets version floor"
```

---

### Task 3: Funktionale Verifikation, Docs, Push

**Files:**
- Create: `/tmp/opencode/run_gate_scenarios.sh` (nur Temp, wird nicht committet)
- Modify: `docs/superpowers/plans/2026-11-15-pipewire-cleanup-safety-gate.md` (Häkchen)
- Commit: `docs/superpowers/specs/2026-11-15-pipewire-cleanup-safety-gate-design.md`, `docs/superpowers/plans/2026-11-15-pipewire-cleanup-safety-gate.md`

**Interfaces:**
- Consumed: Task 1+2 (Funktionsdatei muss `bash -n` bestanden haben).

- [x] **Step 1: Funktions-Harness schreiben**

Harness lädt nur die Funktionsdefinitionen (`head -n -2 install_inferno.sh > /tmp/opencode/ifn_funcs.sh`) und testet mit gestubbten Helfern (`run_cmd_sudo`/`run_as_user` → echo, `apt-get` → Fake-Ausgabe). Fünf Szenarien, je mit erwartetem Ergebnis:

| # | Setup | Erwartung |
|---|-------|-----------|
| A | `TEST_MODE=true`, `prompt_select`→`Cleanup only`, `main` | Exit 0, Gate-Auswertung lief, Meldung `Purge uebersprungen (Schutzgate)` **oder** Dry-Run-Purge (je nach echtem System), kein `command not found`/`awk:`/`unbound` |
| B | Fake-`apt-get` mit Kaskade-Output (Sample aus Test 1), `TEST_MODE=true`, `step_pipewire_cleanup` | Enthält `Purge uebersprungen (Schutzgate)` + `cinnamon` in der Liste, **keine** Zeile `sudo apt-get purge --no-auto-remove -y`, Exit 0 |
| C | Fake-`apt-get` sauber (REMOVED nur Familien), `TEST_MODE=true` | Enthält Dry-Run-Zeile `sudo apt-get purge --no-auto-remove -y pipewire ...`, **keine** Schutzgate-Meldung, Exit 0 |
| D | Fake-`apt-get` mit `exit 100`, `TEST_MODE=true` | `APT-Simulation fehlgeschlagen`, kein Purge, Exit 0 (set -e überlebt) |
| E | `TEST_MODE=false`, Stub-Helfer, echtes `pipewire --version` (1.7.0), `install_cleanup=true`, stdin `y`+`PURGE` an `step_pipewire` | `already installed` → Rebuild-Prompt → `PipeWire Cleanup` → Build-Fortsetzung, Exit 0 |
| F | wie E, aber stdin `n` | `bleibt erhalten`, **kein** `PipeWire Cleanup` im Output, Exit 0 |

Fake-Kaskaden-Output für B: das Sample aus `test_cleanup_gate_parses_apt_simulation_cascade` (identisch, damit Parser und Harness zusammenpassen).

- [x] **Step 2: Harness ausführen**

Run: `bash /tmp/opencode/run_gate_scenarios.sh`
Expected: Alle Szenarien wie in der Tabelle; zusätzlich globale Fehlersuche `grep -iE "command not found|Befehl nicht gefunden|unbound|awk:|syntax error|Traceback" <logs>` → keine Treffer.

- [x] **Step 3: Vollständige Verifikation**

```bash
bash -n install_inferno.sh
QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/ -q   # erwartet: 110 passed
/home/jacob/.local/bin/uvx ruff check .   # erwartet: 273 errors (Baseline, darf nicht steigen)
```

- [x] **Step 4: Docs committen und pushen**

```bash
git add docs/superpowers/specs/2026-11-15-pipewire-cleanup-safety-gate-design.md docs/superpowers/plans/2026-11-15-pipewire-cleanup-safety-gate.md
git commit -m "docs: safety gate + optional rebuild design and plan"
git push
```

Ergebnis-Report an den User: geänderte Dateien, Schutzmechanismus, Testergebnisse (knapp, Deutsch).
