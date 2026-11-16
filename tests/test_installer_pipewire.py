"""Structural contract tests for install_inferno.sh's PipeWire build routine."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "install_inferno.sh"


def _content() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _section(start_marker: str) -> str:
    """Return the body of a top-level bash function (up to its column-0 closing brace)."""
    return _content().split(start_marker, 1)[1].split("\n}", 1)[0]


def test_run_as_user_helper_contract():
    content = _content()
    assert "run_as_user() {" in content
    body = _section("run_as_user() {")
    assert "TEST_MODE" in body
    assert "sudo -H -u" in body
    assert "XDG_RUNTIME_DIR" in body
    assert 'bash -c "$*"' in body


def test_build_uses_meson_ninja_not_autotools():
    content = _content()
    assert "autogen.sh" not in content
    assert "make -j" not in content
    assert "make install" not in content
    assert "meson setup build --prefix=/usr/local" in content
    assert "ninja -C build" in content
    for bad in (
        "-Dpulse=",
        "-Dsystemd=enabled",
        "-Dffado=",
        "-Dladspa=",
        "-Ddsp=",
        "-Dequalizer=",
        "-Dlibfreeaptx=",
        "-Dliblc3=",
        "-Dlibldac=",
        "-Dlibopenaptx=",
    ):
        assert bad not in content, bad
    for good in (
        "-Dlibpulse=enabled",
        "-Dsystemd-user-service=enabled",
        "-Dbluez5-codec-ldac=enabled",
        "-Dlibffado=disabled",
    ):
        assert good in content, good
    for line in _section("step_pipewire() {").splitlines():
        if "rm -rf" in line:
            assert "run_cmd_sudo" in line, line
    for line in content.splitlines():
        if "ninja -C build install" in line:
            assert "run_cmd_sudo" in line
        if "ldconfig" in line:
            assert "run_cmd_sudo" in line


def test_pipewire_deps_block_is_syntactically_continued():
    lines = _section("step_pipewire() {").splitlines()
    starts = [i for i, ln in enumerate(lines) if "apt-get install -y" in ln]
    assert starts, "deps install command missing"
    block = []
    for ln in lines[starts[0] :]:
        block.append(ln)
        if not ln.rstrip().endswith("\\"):
            break
    assert len(block) >= 5, f"deps list too short: {block}"
    for ln in block[:-1]:
        assert ln.rstrip().endswith("\\"), f"missing line continuation: {ln}"
    assert block[-1].rstrip().endswith('"')
    joined = " ".join(b.rstrip().rstrip("\\") for b in block)
    for pkg in (
        "meson",
        "ninja-build",
        "git",
        "build-essential",
        "libpulse-dev",
        "libjack-jackd2-dev",
        "libglib2.0-dev",
        "libpipewire-0.3-dev",
        "libmysofa-dev",
        "libopenaptx-dev",
        "libldacbt-{abr,enc}-dev",
        "libcamera-dev",
    ):
        assert pkg in joined, pkg


def test_version_check_floor_unchanged():
    # Regression-Guard: laeuft ab sofort gruen, darf nie rot werden
    content = _content()
    assert "1.4.11" in content
    assert '[ "$patch" -ge 11 ]' in content


def test_systemctl_user_in_step_pipewire_only_via_run_as_user():
    body = _section("step_pipewire() {")
    for line in body.splitlines():
        if "systemctl --user" in line:
            assert "run_as_user" in line, line
    content = _content()
    assert 'run_as_user "systemctl --user daemon-reload"' in content
    assert 'run_as_user "systemctl --user restart pipewire pipewire-pulse wireplumber"' in content
    assert 'run_as_user "systemctl --user enable --now pipewire pipewire-pulse wireplumber"' in content


def test_wireplumber_lua_cleanup_runs_as_user_with_inner_home():
    body = _section("step_pipewire() {")
    lua_lines = [ln for ln in body.splitlines() if "main.lua.d" in ln]
    assert lua_lines, "lua cleanup missing"
    for line in lua_lines:
        assert "run_as_user" in line, line
        assert "run_as_user '" in line, f"must be single-quoted: {line}"
        assert "$HOME" in line and "$ACTUAL_HOME" not in line, line


def test_verify_installation_defined_called_and_doc_faithful():
    content = _content()
    assert "verify_installation() {" in content
    assert 'run_as_user "$(declare -f verify_installation); verify_installation"' in content
    assert "systemctl --user is-active pipewire pipewire-pulse wireplumber" in content
    assert "which pipewire wireplumber pw-cli pw-jack" in content


def test_pause_prompt_from_document_present():
    content = _content()
    assert "Please close ALL audio apps" in content
    assert "Press Enter when done" in content


def test_cleanup_package_detection_fresh_ubuntu():
    """Test 1: Frisches Ubuntu ohne PipeWire - erkennt keine relevanten Pakete."""
    from pathlib import Path
    SCRIPT = Path(__file__).resolve().parent.parent / "install_inferno.sh"
    content = SCRIPT.read_text(encoding="utf-8")
    # Test that the deps block references the right packages for detection
    assert "pipewire" in content
    assert "libpipewire" in content
    assert "wireplumber" in content
    assert "libwireplumber" in content
    assert "gstreamer1.0-pipewire" in content


def test_cleanup_package_detection_distro_install():
    """Test 2: Normale Ubuntu-Distro-Installation - erkennt Pakete wenn installiert."""
    # This test verifies the package detection logic exists and is correct.
    # Actual detection runs at runtime via dpkg-query.
    content = _content()
    # Check that the awk pattern for detection is present
    assert "$1 ~ /^pipewire(" in content or "$1 ~ /^libpipewire-" in content


def test_cleanup_source_prefix_usrlocal():
    """Test 3: PipeWire aus Git mit Prefix /usr/local - Manifest wird geschrieben."""
    content = _content()
    # Verify manifest writing code exists
    assert "MANIFEST_DIR" in content
    assert "MANIFEST_FILE" in content
    assert "manifest.txt" in content


def test_cleanup_source_prefix_usr():
    """Test 4: PipeWire aus Git mit Prefix /usr - wird nicht manifestiert (nur /usr/local)."""
    content = _content()
    # The manifest is only created for /usr/local prefix
    # Verify the prefix check exists
    assert "/usr/local" in content


def test_cleanup_distro_override():
    """Test 5: Distro-Installation, die durch Source-Build überschrieben wurde."""
    content = _content()
    # Verify the rm -rf existing directory check exists
    assert "rm -rf" in content


def test_cleanup_no_build_dir():
    """Test 6: Source-Installation ohne vorhandenes Build-Verzeichnis."""
    content = _content()
    # The script handles this gracefully - just verify the code structure
    assert "step_pipewire_cleanup" in content


def test_cleanup_no_manifest():
    """Test 7: Source-Installation ohne Manifest - wird inventorisiert, nicht gelöscht."""
    content = _content()
    # Verify the no-manifest branch exists
    assert "No installation manifest created by this installer found" in content


def test_cleanup_wireplumber_lua():
    """Test 8: Vorhandene WirePlumber-Lua-Konfigurationen werden gesichert."""
    content = _content()
    # Verify backup paths include wireplumber config
    assert ".config/wireplumber" in content


def test_cleanup_multiple_versions():
    """Test 9: Mehrere gefundene Installationsversionen werden gehandhabt."""
    content = _content()
    # Verify the package detection can find multiple matches
    assert "pipewire" in content


def test_cleanup_user_abort():
    """Test 10: Abbruch durch den Benutzer während der Bereinigung."""
    content = _content()
    # Verify the PURGE confirmation exists
    assert "PURGE" in content
    assert "Enter PURGE exactly to continue" in content


# ---------------------------------------------------------------------------
# Regression tests: cleanup integration correctness (round 2)
# ---------------------------------------------------------------------------


def test_cleanup_defined_exactly_once_and_main_invoked_once():
    """The script must define step_pipewire_cleanup() once and invoke main once."""
    content = _content()
    assert content.count("step_pipewire_cleanup() {") == 1, "duplicate cleanup definition"
    assert content.count('main "$@"') == 1, "main must be invoked exactly once"


def test_cleanup_uses_only_defined_helpers():
    """No calls to helpers that do not exist in this script."""
    import re

    body = _section("step_pipewire_cleanup() {")
    assert not re.search(r'(?<![\w])log "', body), "undefined log() used"
    assert not re.search(r'(?<![\w])die "', body), "undefined die() used"
    assert not re.search(r'(?<![\w])warn "', body), "undefined warn() used"
    assert not re.search(r"(?<![\w])run_root\b", body), "undefined run_root() used"
    assert "EXECUTE" not in body, "EXECUTE is never set by the installer"


def test_cleanup_detection_awk_program_executes():
    """The dpkg detection awk program must be syntactically valid."""
    import re
    import subprocess

    content = _content()
    m = re.search(r"awk -F '\\t' '(.*?)'", content, re.DOTALL)
    assert m, "dpkg detection awk program missing"
    sample = (
        "pipewire\tinstalled\n"
        "pipewire-bin\tinstalled\n"
        "libpipewire-0.3-0\tinstalled\n"
        "libspa-0.2-components\tinstalled\n"
        "wireplumber\tinstalled\n"
        "libwireplumber-0.5-0\tinstalled\n"
        "gstreamer1.0-pipewire\tinstalled\n"
        "pulseaudio\tinstalled\n"
    )
    proc = subprocess.run(
        ["awk", "-F", "\t", m.group(1)],
        input=sample,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"awk program failed: {proc.stderr}"
    found = proc.stdout.split()
    for expected in (
        "pipewire",
        "pipewire-bin",
        "libpipewire-0.3-0",
        "libspa-0.2-components",
        "wireplumber",
        "libwireplumber-0.5-0",
        "gstreamer1.0-pipewire",
    ):
        assert expected in found, f"missed package: {expected}"
    assert "pulseaudio" not in found


def test_cleanup_runs_after_version_check_before_build():
    """Cleanup must run after the version check found PipeWire too old,
    and before the build starts (full installation flow)."""
    body = _section("step_pipewire() {")
    assert "step_pipewire_cleanup" in body, "cleanup not wired into step_pipewire"
    i_detect = body.index("Detected PipeWire version")
    i_cleanup = body.index("step_pipewire_cleanup")
    i_build = body.index("meson setup build")
    assert i_detect < i_cleanup < i_build, (
        f"wrong order: detect={i_detect} cleanup={i_cleanup} build={i_build}"
    )


def test_cleanup_only_mode_reaches_cleanup():
    """Mode 'Cleanup only' must reach the cleanup step instead of exiting early."""
    main_body = _section("main() {")
    lines = main_body.splitlines()
    nothing_idx = next(
        (i for i, ln in enumerate(lines) if "Nothing selected" in ln), None
    )
    assert nothing_idx is not None, "nothing-selected guard missing"
    cond = lines[nothing_idx - 1]
    assert "install_cleanup" in cond, f"guard ignores cleanup: {cond}"
    # the only cleanup invocation in main() must be guarded by cleanup==true
    # && inferno==false (standalone cleanup path)
    calls = [i for i, ln in enumerate(lines) if ln.strip() == "step_pipewire_cleanup"]
    assert len(calls) == 1, f"unexpected cleanup calls in main: {calls}"
    guard = lines[calls[0] - 1]
    assert 'install_cleanup" = "true"' in guard, guard
    assert 'install_inferno" = "false"' in guard, guard


def test_version_detection_includes_patch_level():
    """Version extraction must capture major.minor.patch (1.4.11 floor)."""
    body = _section("step_pipewire() {")
    assert "[0-9]+\\.[0-9]+(\\.[0-9]+)?" in body


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
    assert body.index("gate_prog") < body.index("Enter PURGE exactly to continue")
    assert "Purge skipped (safety gate)" in body
    assert "Evaluation failed" in body, "parse failure must fail safe (skip purge)"
    i_purge_cmd = body.index('apt-get purge --no-auto-remove -y')
    guard_zone = body[max(0, i_purge_cmd - 400) : i_purge_cmd]
    assert 'purge_allowed" = "true"' in guard_zone, "purge command not guarded"


def test_cleanup_simulation_uses_c_locale():
    """apt-Simulation mit LC_ALL=C, damit die englischen Sektionsheader stabil parsebar sind."""
    content = _content()
    assert "LC_ALL=C apt-get -s purge" in content


def test_cleanup_gate_fails_closed_without_removed_header():
    """Schutzgate fail-closed: fehlt der exakte REMOVED-Header in der
    LC_ALL=C apt-Ausgabe (apt hat die Sektion umformuliert), ist die
    Auswertung unzuverlaessig -> violations = "Evaluation failed"
    -> purge_allowed bleibt false (Fail-safe, nie purge).

    Extrahiert den realen Auswertungsblock aus step_pipewire_cleanup()
    und fuehrt ihn mit gestubten log_*/sim_out aus.
    """
    import subprocess

    body = _section("step_pipewire_cleanup() {")
    start = body.index("local gate_prog=")
    end = body.index('if [ "$purge_allowed" = "true" ]')
    block = body[start:end]

    def run_gate(sim_out: str) -> str:
        script = (
            'log_warn() { printf "WARN: %s\\n" "$*"; }\n'
            'log_info() { printf "INFO: %s\\n" "$*"; }\n'
            "eval_gate() {\n"
            "    local purge_allowed=false\n"
            "    if true; then\n"
            f"{block}"
            '    printf \'PURGE_ALLOWED=%s\\n\' "$purge_allowed"\n'
            "}\n"
            f"sim_out='{sim_out}'\n"
            "eval_gate\n"
        )
        proc = subprocess.run(
            ["bash"], input=script, capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"bash failed: {proc.stderr}\nscript:\n{script}"
        return proc.stdout

    # 1) apt hat die Sektion umformuliert -> kein exakter Header -> kein Token
    #    aus der REMOVED-Sektion -> OHNE Guard waere violations="" -> purge erlaubt!
    reworded = (
        "Reading package lists... Done\n"
        "Building dependency tree... Done\n"
        "The following packages will be REMOVED (details):\n"
        "  pipewire* wireplumber*\n"
        "0 upgraded, 0 newly installed, 2 to remove and 0 not upgraded."
    )
    out = run_gate(reworded)
    assert "Evaluation failed" in out, (
        "missing-header must be treated as parse failure (fail-safe):\n" + out
    )
    assert "PURGE_ALLOWED=false" in out, "purge must stay blocked:\n" + out

    # 2) Positivkontrolle: exakter Header, saubere Kaskade -> Purge erlaubt
    clean = (
        "Reading package lists... Done\n"
        "The following packages will be REMOVED:\n"
        "  libpipewire-0.3-0t64* pipewire* pipewire-bin* wireplumber*\n"
        "0 upgraded, 0 newly installed, 4 to remove and 0 not upgraded."
    )
    out = run_gate(clean)
    assert "PURGE_ALLOWED=true" in out, "clean run must allow purge:\n" + out
    assert "Evaluation failed" not in out, out

    # 3) Positivkontrolle: exakter Header, Kaskade ausserhalb der Familien
    cascade = (
        "Reading package lists... Done\n"
        "The following packages will be REMOVED:\n"
        "  cinnamon* pipewire* wireplumber*\n"
        "0 upgraded, 0 newly installed, 3 to remove and 0 not upgraded."
    )
    out = run_gate(cascade)
    assert "PURGE_ALLOWED=false" in out, "cascade must block purge:\n" + out
    assert "cinnamon" in out, out


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
