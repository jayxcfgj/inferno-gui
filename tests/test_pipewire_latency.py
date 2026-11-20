"""Tests for the read-only PipeWire latency estimate helper.

core.pipewire_latency.read_pipewire_latency() shells out to
``sudo -u <user> env K=V ... pw-metadata -n settings`` — the read runs
in the INVOKING user's context, because the pipewire daemon in the
user's runtime session rejects (or lacks the session env for) a root
peer — with the session env from core.pipewire_env riding as
target-side env command arguments where sudo env_reset cannot strip
them. All subprocess activity is mocked here; the import-order tests
run real fresh interpreters via subprocess.
"""
import logging
import os
import pwd
import subprocess
import sys
import unittest.mock as mock

from inferno_gui.core import pipewire_latency


# Fixture mimicking real `pw-metadata -n settings` output (relevant lines).
FIXTURE_OUTPUT = (
    "Info: objects managed by pipewire\n"
    "[settings]\n"
    "  clock.force-quantum = 0\n"
    "  clock.quantum = 1024\n"
    "  clock.max-quantum = 2048\n"
    "  clock.force-rate = 0\n"
    "  clock.rate = 48000\n"
    "  clock.max-rate = 96000\n"
)

# Fixture from a self-built PipeWire >= 1.4.11: newer pw-metadata prints
# the QUOTED format (`key:'...' value:'...'` lines) instead of the plain
# `key = value` form.
QUOTED_FIXTURE_OUTPUT = (
    'Found "settings" metadata 33\n'
    "update: id:0 key:'log.level' value:'2' type:''\n"
    "update: id:0 key:'clock.rate' value:'48000' type:''\n"
    "update: id:0 key:'clock.allowed-rates' value:'[ 48000 ]' type:''\n"
    "update: id:0 key:'clock.quantum' value:'1024' type:''\n"
    "update: id:0 key:'clock.min-quantum' value:'32' type:''\n"
    "update: id:0 key:'clock.max-quantum' value:'2048' type:''\n"
    "update: id:0 key:'clock.force-quantum' value:'0' type:''\n"
)


def _patch_run(stdout, returncode=0):
    """Patch subprocess.run to return a completed result with stdout."""
    result = mock.Mock(returncode=returncode, stdout=stdout, stderr="")
    return mock.patch("subprocess.run", return_value=result)


def test_parses_quantum_rate_and_math():
    with _patch_run(FIXTURE_OUTPUT):
        result = pipewire_latency.read_pipewire_latency()
    assert result == {
        "quantum": 1024,
        "rate": 48000,
        "headroom": 128,
        "per_direction_ms": 24.0,
        "round_trip_ms": 48.0,
        "source": "pw-metadata",
    }


def test_custom_headroom_used_in_math():
    with _patch_run(FIXTURE_OUTPUT):
        result = pipewire_latency.read_pipewire_latency(headroom_frames=256)
    assert result is not None
    assert result["headroom"] == 256
    assert result["per_direction_ms"] == (1024 + 256) / 48000 * 1000
    assert result["round_trip_ms"] == 2 * result["per_direction_ms"]


def test_parses_quoted_metadata_format():
    """Newer PipeWire (>= 1.4.11) prints the quoted format
    ``key:'clock.quantum' value:'1024'`` instead of ``clock.quantum =
    1024`` — the parser must accept either shape."""
    with _patch_run(QUOTED_FIXTURE_OUTPUT):
        result = pipewire_latency.read_pipewire_latency()
    assert result == {
        "quantum": 1024,
        "rate": 48000,
        "headroom": 128,
        "per_direction_ms": 24.0,
        "round_trip_ms": 48.0,
        "source": "pw-metadata",
    }


def test_plain_decoy_keys_not_matched():
    """Decoy keys (force/min/max variants) must never satisfy the read,
    in either output format."""
    decoy_output = (
        "  clock.force-quantum = 0\n"
        "  clock.min-quantum = 32\n"
        "  clock.max-quantum = 2048\n"
        "  clock.force-rate = 0\n"
        "  clock.max-rate = 96000\n"
    )
    with _patch_run(decoy_output):
        assert pipewire_latency.read_pipewire_latency() is None


def test_quoted_decoy_keys_not_matched():
    """Quoted decoy lines (``key:'clock.force-quantum' value:'0'`` etc.)
    must never be picked up as the quantum/rate values."""
    decoy_output = (
        "update: id:0 key:'clock.min-quantum' value:'32' type:''\n"
        "update: id:0 key:'clock.max-quantum' value:'2048' type:''\n"
        "update: id:0 key:'clock.force-quantum' value:'0' type:''\n"
        "update: id:0 key:'clock.max-rate' value:'96000' type:''\n"
    )
    with _patch_run(decoy_output):
        assert pipewire_latency.read_pipewire_latency() is None


def test_missing_tool_returns_none():
    with mock.patch("subprocess.run", side_effect=FileNotFoundError("no pw-metadata")):
        assert pipewire_latency.read_pipewire_latency() is None


def test_timeout_returns_none():
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pw-metadata", timeout=2)):
        assert pipewire_latency.read_pipewire_latency() is None


def test_garbage_output_returns_none():
    with _patch_run("some unrelated garbage with no clock lines here"):
        assert pipewire_latency.read_pipewire_latency() is None


def test_partial_output_missing_rate_returns_none():
    with _patch_run("  clock.quantum = 1024\n"):
        assert pipewire_latency.read_pipewire_latency() is None


def test_partial_output_missing_quantum_returns_none():
    with _patch_run("  clock.rate = 48000\n"):
        assert pipewire_latency.read_pipewire_latency() is None


# ── failure diagnostics (WARNING logs) ─────────────────────────
# The GUI runs as root with stderr visible in the user's terminal:
# a failed read must say WHY (logging's last-resort handler prints
# WARNING+ to stderr), not just silently degrade to "unknown".


def _warnings(caplog):
    """WARNING records from the helper's module logger."""
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def test_timeout_logs_warning(caplog):
    """A timeout logs a one-line WARNING naming the elapsed time."""
    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pw-metadata", timeout=2),
    ):
        with caplog.at_level(
            logging.WARNING, logger="inferno_gui.core.pipewire_latency"
        ):
            assert pipewire_latency.read_pipewire_latency() is None
    warns = _warnings(caplog)
    assert warns, f"no WARNING logged on timeout: {caplog.text!r}"
    assert any("timed out" in r.getMessage() for r in warns), caplog.text
    assert any("2" in r.getMessage() for r in warns), \
        f"timeout WARNING lacks the elapsed seconds: {caplog.text!r}"


def test_nonzero_exit_logs_warning_with_rc_and_tail(caplog):
    """A nonzero exit logs rc plus the tail of stderr+stdout."""
    with _patch_run("boom: connection refused", returncode=3):
        with caplog.at_level(
            logging.WARNING, logger="inferno_gui.core.pipewire_latency"
        ):
            assert pipewire_latency.read_pipewire_latency() is None
    warns = _warnings(caplog)
    assert warns, f"no WARNING logged on nonzero exit: {caplog.text!r}"
    assert any("rc=3" in r.getMessage() for r in warns), caplog.text
    assert any("boom: connection refused" in r.getMessage() for r in warns), \
        f"nonzero-exit WARNING lacks the output tail: {caplog.text!r}"


def test_unparseable_output_logs_warning(caplog):
    """Output without clock lines logs a WARNING with an output excerpt."""
    with _patch_run("some unrelated garbage with no clock lines here"):
        with caplog.at_level(
            logging.WARNING, logger="inferno_gui.core.pipewire_latency"
        ):
            assert pipewire_latency.read_pipewire_latency() is None
    warns = _warnings(caplog)
    assert warns, f"no WARNING logged on unparseable output: {caplog.text!r}"
    assert any("unparseable" in r.getMessage() for r in warns), caplog.text
    assert any("some unrelated garbage" in r.getMessage() for r in warns), \
        f"unparseable WARNING lacks the output head: {caplog.text!r}"


def test_runs_pw_metadata_as_invoking_user(monkeypatch):
    """pw-metadata runs in the INVOKING user's context: the command is
    ``sudo -u <user> env K=V ... pw-metadata -n settings`` — a root peer
    is exactly what the user-session daemon rejects, so the read must
    delegate to the user.  The session env (the same two keys
    core.pipewire_env.get_pipewire_env forces) rides as target-side env
    arguments where sudo env_reset cannot strip it; timeout/env kwargs
    stay as they were."""
    me = pwd.getpwuid(os.getuid())
    monkeypatch.setenv("SUDO_USER", me.pw_name)

    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return mock.Mock(returncode=0, stdout=FIXTURE_OUTPUT, stderr="")
    with mock.patch("subprocess.run", side_effect=fake_run):
        result = pipewire_latency.read_pipewire_latency()

    assert result is not None
    cmd, = captured["args"]
    assert cmd == [
        "sudo", "-u", me.pw_name, "env",
        f"XDG_RUNTIME_DIR=/run/user/{me.pw_uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{me.pw_uid}/bus",
        "pw-metadata", "-n", "settings",
    ], f"pw-metadata must run as the invoking user: {cmd}"
    assert captured["timeout"] == 2
    assert captured["capture_output"] is True
    assert captured["text"] is True
    # The subprocess env stays as-is: the forced user-session keys.
    env = captured["env"]
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{me.pw_uid}"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == \
        f"unix:path=/run/user/{me.pw_uid}/bus"


def test_user_resolution_without_sudo_user(monkeypatch):
    """No SUDO_USER: the target is the owner of the actual user's home
    (same resolution as ui.url_utils._target_user)."""
    from inferno_gui.core.config import get_actual_user_home

    monkeypatch.delenv("SUDO_USER", raising=False)
    owner = pwd.getpwuid(get_actual_user_home().stat().st_uid).pw_name
    uid = pwd.getpwnam(owner).pw_uid

    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        return mock.Mock(returncode=0, stdout=FIXTURE_OUTPUT, stderr="")

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = pipewire_latency.read_pipewire_latency()

    assert result is not None
    cmd, = captured["args"]
    assert cmd[:3] == ["sudo", "-u", owner], \
        f"without SUDO_USER the target must be the home owner: {cmd}"
    assert cmd[3] == "env"
    assert f"XDG_RUNTIME_DIR=/run/user/{uid}" in cmd
    assert f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus" in cmd
    assert cmd[-3:] == ["pw-metadata", "-n", "settings"]


def test_helper_is_read_only_and_never_raises(monkeypatch):
    """Any non-expected exception path must not leak as a raise."""
    with mock.patch("subprocess.run", side_effect=OSError("permission denied")):
        try:
            result = pipewire_latency.read_pipewire_latency()
        except OSError:
            raise AssertionError("helper must never raise")
    assert result is None


# ── import order (circular-import regression) ─────────────────


def _fresh_interpreter_import(module: str):
    """Import `module` in a clean interpreter; return the CompletedProcess."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, text=True, timeout=60,
        cwd=repo_root,
    )


def test_fresh_interpreter_imports_helper_first():
    """Importing the helper FIRST must not hit a partially initialized
    module: core.pipewire_latency must not import from ui.* (which
    pulls main_window → settings_tab → back into pipewire_latency)."""
    proc = _fresh_interpreter_import("inferno_gui.core.pipewire_latency")
    assert proc.returncode == 0, \
        f"helper-first import failed:\n{proc.stderr}"


def test_fresh_interpreter_imports_ui_first():
    """The UI-first import order must also stay clean."""
    proc = _fresh_interpreter_import("inferno_gui.ui.control_tab")
    assert proc.returncode == 0, f"ui-first import failed:\n{proc.stderr}"


def test_helper_imports_env_from_core_not_ui():
    """The env helper must live in a stdlib-only core module: importing
    inferno_gui.core.pipewire_latency must not drag in PyQt6 at all."""
    proc = _fresh_interpreter_import(
        "inferno_gui.core.pipewire_latency as m;"
        "import sys;"
        "assert not any(mod.startswith('PyQt6') for mod in sys.modules), "
        "'PyQt6 leaked into the helper import: ' + "
        "str([m for m in sys.modules if m.startswith('PyQt6')])")
    assert proc.returncode == 0, \
        f"helper import pulls PyQt6:\n{proc.stdout}{proc.stderr}"


# ── never-raises hardening ────────────────────────────────────


def test_nonzero_exit_returns_none():
    """pw-metadata exiting nonzero is a failure, even when the output
    happens to contain parseable clock lines."""
    with _patch_run(FIXTURE_OUTPUT, returncode=1):
        assert pipewire_latency.read_pipewire_latency() is None


def test_malformed_numeric_output_returns_none():
    """Non-numeric clock values must degrade to None, never raise."""
    with _patch_run("clock.quantum = abc\nclock.rate = 48000\n"):
        assert pipewire_latency.read_pipewire_latency() is None


def test_non_text_output_returns_none():
    """Non-text stdout (e.g. bytes from a broken pipe) must degrade to
    None, never raise TypeError."""
    with _patch_run(b"clock.quantum = 1024\nclock.rate = 48000\n"):
        assert pipewire_latency.read_pipewire_latency() is None


def test_decode_error_inside_run_returns_none():
    """subprocess.run itself raising UnicodeDecodeError — with text=True
    the output decode happens INSIDE run(), so a real decode failure
    escapes the call — must degrade to None, never raise."""
    with mock.patch(
        "subprocess.run",
        side_effect=UnicodeDecodeError("utf-8", b"x", 0, 1, "start"),
    ):
        assert pipewire_latency.read_pipewire_latency() is None
