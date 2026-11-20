"""Tests for the read-only PipeWire latency estimate helper.

core.pipewire_latency.read_pipewire_latency() shells out to
``pw-metadata -n settings`` (with the user-session env from
core.pipewire_env.get_pipewire_env) and estimates graph latency from
quantum/rate. All subprocess activity is mocked here; the import-order
tests run real fresh interpreters via subprocess.
"""
import os
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


def test_forwards_pipewire_env_and_timeout():
    """The helper must pass _get_pipewire_env()'s env and timeout=2."""
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return mock.Mock(returncode=0, stdout=FIXTURE_OUTPUT, stderr="")

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = pipewire_latency.read_pipewire_latency()

    assert result is not None
    assert captured["args"] == (["pw-metadata", "-n", "settings"],)
    assert captured["timeout"] == 2
    assert captured["capture_output"] is True
    assert captured["text"] is True
    env = captured["env"]
    # No SUDO_USER: the helper targets the invoking user's runtime dir.
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{os.getuid()}"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path=/run/user/{os.getuid()}/bus"


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
