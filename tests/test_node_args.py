# tests/test_node_args.py
"""Node-Args-Tests: sink_cmd/source_cmd muessen schlichte key=value-Tokens sein.

Regression (86d36dd): frueher war das erste Property-Arg '{'object.linger=1'
und die Liste endete auf '}' - pw-cli bekam damit kein object.linger.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_node_args.py -q
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QSettings, QProcess

# QSettings-Speicher auf ein Temp-Verzeichnis umleiten, damit die echten
# User-Settings (~/.config/InfernoGUI) von keinem Test angefasst werden.
_TEMPS = tempfile.mkdtemp(prefix="inferno-gui-test-settings-")
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, _TEMPS)


class _Signal:
    """Minimal-Ersatz fuer ein Qt-Signal (nur connect wird benoetigt)."""

    def connect(self, *args, **kwargs):
        pass


class _RecordingQProcess:
    """QProcess-Ersatz, der start()-Argumente mitprotokolliert (kein echter Prozess)."""

    ProcessState = QProcess.ProcessState

    readyReadStandardOutput = _Signal()
    readyReadStandardError = _Signal()
    finished = _Signal()

    commands = []

    def start(self, program, args=None):
        _RecordingQProcess.commands.append([program] + list(args or []))

    def waitForFinished(self, timeout=None):
        return True

    def exitCode(self):
        return 0

    def state(self):
        return QProcess.ProcessState.NotRunning

    def readAllStandardOutput(self):
        return b""


# PyQt haelt keine Referenz auf die QApplication: wird der Python-Wrapper
# garbage-collected, zerstoert Qt die App samt aller Widgets. Deshalb
# die Referenz modulglobal halten.
_APP = None


def _get_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _capture_node_commands(monkeypatch):
    """_create_pipewire_nodes ausfuehren und die gesendeten Befehle zurueckgeben."""
    _get_app()

    import inferno_gui.ui.control_tab as ct_mod
    import inferno_gui.core.config as cfg_mod
    from inferno_gui.ui.control_tab import ControlTab

    monkeypatch.setattr(ct_mod, "QProcess", _RecordingQProcess)
    monkeypatch.setattr(cfg_mod, "get_statime_binary", lambda: Path("/bin/sh"))
    config_tmp = Path(tempfile.mkdtemp(prefix="inferno-test-config-")) / "statime-v2.toml"
    monkeypatch.setattr(cfg_mod, "get_default_statime_config", lambda v="v2": config_tmp)

    ct = ControlTab()
    _RecordingQProcess.commands = []
    ct._create_pipewire_nodes()
    return _RecordingQProcess.commands


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
