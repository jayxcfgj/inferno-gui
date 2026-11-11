# tests/test_node_args.py
"""Node-Args-Tests: sink_cmd/source_cmd muessen schlichte key=value-Tokens sein.

Regression (86d36dd): frueher war das erste Property-Arg '{'object.linger=1'
und die Liste endete auf '}' - pw-cli bekam damit kein object.linger.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_node_args.py -q
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QProcess, QSettings

# QSettings-Speicher auf ein Temp-Verzeichnis umleiten, damit die echten
# User-Settings (~/.config/InfernoGUI) von keinem Test angefasst werden.
_TEMPS = tempfile.mkdtemp(prefix="inferno-gui-test-settings-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)


class _Signal:
    """Minimal-Ersatz fuer ein Qt-Signal (nur connect wird benoetigt)."""

    def connect(self, *args, **kwargs):
        pass


class _RecordingQProcess:
    """QProcess-Ersatz, der start()-Argumente mitprotokolliert (kein echter Prozess).

    Verhalten pro Aufruf ist ueber Klassenattribute konfigurierbar: Listen werden
    in start()-Reihenfolge abgearbeitet (pop(0)); ist die Liste leer, gilt der
    Default (Exit 0, leeres stderr, waitForFinished True).
    """

    ProcessState = QProcess.ProcessState

    readyReadStandardOutput = _Signal()
    readyReadStandardError = _Signal()
    finished = _Signal()

    commands = []
    pending_exit_codes = []   # pro create-Aufruf: exitCode() oder 0
    pending_stderrs = []      # pro create-Aufruf: readAllStandardError() oder b""
    pending_timeouts = []     # pro create-Aufruf: waitForFinished()-Return oder True

    def start(self, program, args=None):
        _RecordingQProcess.commands.append([program] + list(args or []))

    def terminate(self):
        pass

    def kill(self):
        pass

    def waitForFinished(self, timeout=None):
        if _RecordingQProcess.pending_timeouts:
            return _RecordingQProcess.pending_timeouts.pop(0)
        return True

    def exitCode(self):
        if _RecordingQProcess.pending_exit_codes:
            return _RecordingQProcess.pending_exit_codes.pop(0)
        return 0

    def state(self):
        return QProcess.ProcessState.NotRunning

    def readAllStandardOutput(self):
        return b""

    def readAllStandardError(self):
        if _RecordingQProcess.pending_stderrs:
            return _RecordingQProcess.pending_stderrs.pop(0)
        return b""


class _FakeResult:
    """subprocess.run-Ersatz fuer `pw-cli ls Node` (kein echter Prozess)."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# Fake-Output von `pw-cli ls Node`: beide Inferno-Nodes vorhanden.
_LS_BOTH = (
    'id 62\ttype PipeWire:Interface:Node\n'
    '\tproperties:\n'
    '\t\tnode.name = "Inferno_sink"\n'
    '\t\tmedia.class = "Audio/Sink"\n'
    'id 63\ttype PipeWire:Interface:Node\n'
    '\tproperties:\n'
    '\t\tnode.name = "Inferno_source"\n'
    '\t\tmedia.class = "Audio/Source"\n'
)

# Fake-Output: Nodes NICHT vorhanden (create schlug still fehl).
_LS_MISSING = (
    'id 62\ttype PipeWire:Interface:Node\n'
    '\tproperties:\n'
    '\t\tnode.name = "alsa_output.usb-0c0c_Something"\n'
)


# PyQt haelt keine Referenz auf die QApplication: wird der Python-Wrapper
# garbage-collected, zerstoert Qt die App samt aller Widgets. Deshalb
# die Referenz modulglobal halten.
_APP = None


def _get_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _run_create(monkeypatch, ls_stdout=_LS_BOTH, exit_codes=None, stderrs=None,
                timeouts=None, run_exc=None):
    """_create_pipewire_nodes ausfuehren und (gesendete Befehle, Log-Text) zurueckgeben.

    QProcess und subprocess.run (`pw-cli ls Node`) sind gemockt: keine echten
    pw-cli-Aufrufe. `ls_stdout` ist der Fake-Output der Verifikation,
    `exit_codes`/`stderrs`/`timeouts` konfigurieren die create-Aufrufe der
    Reihe nach. `run_exc` laesst die Verifikation mit dieser Exception
    scheitern (OSError, TimeoutExpired, ...).
    """
    _get_app()

    import inferno_gui.core.config as cfg_mod
    import inferno_gui.ui.control_tab as ct_mod
    from inferno_gui.ui.control_tab import ControlTab

    monkeypatch.setattr(ct_mod, "QProcess", _RecordingQProcess)
    _RecordingQProcess.pending_exit_codes = list(exit_codes or [])
    _RecordingQProcess.pending_stderrs = list(stderrs or [])
    _RecordingQProcess.pending_timeouts = list(timeouts or [])

    if run_exc is not None:
        def _raise_run(args, **kw):
            raise run_exc
        monkeypatch.setattr(ct_mod.subprocess, "run", _raise_run)
    else:
        monkeypatch.setattr(ct_mod.subprocess, "run",
                            lambda args, **kw: _FakeResult(stdout=ls_stdout))
    monkeypatch.setattr(cfg_mod, "get_statime_binary", lambda: Path("/bin/sh"))
    config_tmp = Path(tempfile.mkdtemp(prefix="inferno-test-config-")) / "statime-v2.toml"
    monkeypatch.setattr(cfg_mod, "get_default_statime_config", lambda v="v2": config_tmp)

    ct = ControlTab()
    _RecordingQProcess.commands = []
    ct._create_pipewire_nodes()
    return _RecordingQProcess.commands, ct.terminal_output.toPlainText()


def _capture_node_commands(monkeypatch):
    """_create_pipewire_nodes ausfuehren und die gesendeten Befehle zurueckgeben."""
    cmds, _log = _run_create(monkeypatch)
    return cmds


def test_sink_and_source_args_are_plain_key_value(monkeypatch):
    cmds = _capture_node_commands(monkeypatch)
    assert len(cmds) == 2
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


def test_success_logged_only_after_verification(monkeypatch):
    # Fake-Verhalten: create-Aufruf exit 0, `pw-cli ls Node` enthaelt beide Namen
    # -> Log enthaelt "Inferno sink created successfully (verified)"
    _cmds, log = _run_create(monkeypatch, ls_stdout=_LS_BOTH)
    assert "Inferno sink created successfully (verified)" in log
    assert "Inferno source created successfully (verified)" in log
    assert "creation FAILED" not in log


def test_missing_node_logs_failure(monkeypatch):
    # `pw-cli ls Node` enthaelt die Namen NICHT -> Log enthaelt "creation FAILED"
    # und NICHT "created successfully"
    _cmds, log = _run_create(monkeypatch, ls_stdout=_LS_MISSING)
    assert log.count("creation FAILED") == 2
    assert "created successfully" not in log


def test_nonzero_exit_logs_failure(monkeypatch):
    # create-Aufruf liefert exitCode 1 + stderr -> Log enthaelt "creation FAILED"
    # und den stderr-Text
    stderr = b"pw-cli: failed to create node: connection refused"
    _cmds, log = _run_create(monkeypatch, exit_codes=[1], stderrs=[stderr])
    assert "Inferno sink creation FAILED" in log
    assert "exit code 1" in log
    assert "failed to create node: connection refused" in log
    # Der zweite Aufruf laeuft normal weiter und wird verifiziert.
    assert "Inferno source created successfully (verified)" in log


def test_stderr_error_logs_failure_even_on_exit_zero(monkeypatch):
    # create-Aufruf exit 0, aber create-stderr enthaelt "error"
    # -> Log enthaelt "creation FAILED" und NICHT "created successfully"
    stderr = b"remote 0: error: node creation rejected"
    _cmds, log = _run_create(monkeypatch, ls_stdout=_LS_BOTH, stderrs=[stderr])
    assert "Inferno sink creation FAILED" in log
    assert "error: node creation rejected" in log
    assert "Inferno sink created successfully" not in log


def test_waitforfinished_timeout_logs_failure_not_success(monkeypatch):
    """IMPORTANT-Regression: waitForFinished-Timeout (False) darf nicht in die
    Verifikation fallen und niemals "created successfully" behaupten."""
    _cmds, log = _run_create(monkeypatch, timeouts=[False])
    assert "Inferno sink creation FAILED: timed out after 10 s" in log
    assert "Inferno sink created successfully" not in log
    assert "Warning: Inferno sink creation timed out" not in log
    assert log.count("creation FAILED") == 1
    # Der zweite Aufruf (source) laeuft normal und wird verifiziert.
    assert "Inferno source created successfully (verified)" in log


def test_subprocess_oserror_logs_failure(monkeypatch):
    """Verifikation wirft OSError (z. B. pw-cli nicht gefunden) -> FAILED-Log,
    kein Crash, kein Erfolgs-Claim."""
    _cmds, log = _run_create(
        monkeypatch, run_exc=OSError("pw-cli not found"))
    assert log.count("creation FAILED") == 2
    assert "pw-cli not found" in log
    assert "created successfully" not in log


def test_verification_timeout_logs_failure(monkeypatch):
    """Verifikation-Timeout (subprocess.TimeoutExpired) -> FAILED-Log
    "verification timed out", kein Crash, kein Erfolgs-Claim."""
    _cmds, log = _run_create(
        monkeypatch, run_exc=subprocess.TimeoutExpired("pw-cli", 2))
    assert log.count("creation FAILED") == 2
    assert "verification timed out" in log
    assert "created successfully" not in log


def test_ls_error_output_logs_failure(monkeypatch):
    """`pw-cli ls Node`-Output enthaelt "error" -> FAILED-Log, kein
    "created successfully"."""
    ls_with_error = _LS_BOTH + "\nsome error while listing nodes\n"
    _cmds, log = _run_create(monkeypatch, ls_stdout=ls_with_error)
    assert log.count("creation FAILED") == 2
    assert "reported an error" in log
    assert "created successfully" not in log
