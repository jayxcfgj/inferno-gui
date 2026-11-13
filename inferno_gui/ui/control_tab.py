"""Control Tab – Main interface for starting/stopping Inferno and PTP."""

import os
import re
import subprocess
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QCheckBox, QProgressBar, QComboBox, QMenu, QStyle,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QProcess, QTimer, QSettings, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor

from inferno_gui.core.config import (
    get_statime_binary,
    get_default_statime_config,
    get_work_dir,
)
from inferno_gui.core.lock_gate import LockGate
from inferno_gui.core.log_parser import StatimeLogParser, LogSeverity, format_log_entry


def _get_pipewire_env() -> dict:
    """Return environment dict for PipeWire commands to connect to the actual user's session.

    When running under sudo (required for PTP hardware timestamping), PipeWire
    commands must target the actual user's PipeWire instance, not root's.
    """
    import os
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user and sudo_user != 'root':
        # Get the actual user's UID
        import pwd
        try:
            uid = pwd.getpwnam(sudo_user).pw_uid
        except KeyError:
            uid = os.getuid()
    else:
        uid = os.getuid()

    env = os.environ.copy()
    env['XDG_RUNTIME_DIR'] = f'/run/user/{uid}'
    env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'
    return env


_MAX_TERMINAL_LINES = 3000
_MAX_RESIDUE = 8192

# ANSI-Escape-Sequenzen (CSI, z.B. Farbcodes \x1b[2m) - statime schreibt
# sie in seinen Stream; sie landen sonst 1:1 im Terminal und zerstoeren
# den Severity-Regex des Parsers (ERROR-Zeile wird zu INFO).
_ANSI_CSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')


def _trim_terminal(edit, max_lines=_MAX_TERMINAL_LINES):
    doc = edit.document()
    if doc.blockCount() > max_lines:
        cursor = edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        remove = doc.blockCount() - max_lines + 100
        for _ in range(remove):
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.deleteChar()


class ControlTab(QWidget):
    """Main control tab with Start/Stop buttons and status."""
    
    # Signals
    inferno_started = pyqtSignal()
    inferno_stopped = pyqtSignal()
    ptp_started = pyqtSignal()
    ptp_stopped = pyqtSignal()
    status_changed = pyqtSignal(dict)  # For session tab
    
    def __init__(self, settings_tab=None):
        super().__init__()
        self.settings_tab = settings_tab
        self.ptp_process: QProcess = None
        self.is_ptp_running = False
        self._ptp_starting = False
        self._ptp_offset = None
        self._ptp_state = ""
        self._ptp_freq = None
        self._interface_ips = {}
        self._settings_dirty = False
        self._lock_gate: LockGate | None = None
        self._awaiting_lock = False
        self._lock_wait_ticks = 0
        
        self.parser = StatimeLogParser(filter_interval=1.0)
        self._stdout_buffer = ''
        self._stderr_buffer = ''
        self._write_timer = QTimer(self)
        self._write_timer.setInterval(50)
        self._write_timer.timeout.connect(self._flush_terminal)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(500)
        self._update_timer.timeout.connect(self._update_status_panel)
        
        # Startup verification timer - verifies PTP process stays running
        self._startup_verify_timer = QTimer(self)
        self._startup_verify_timer.setSingleShot(True)
        self._startup_verify_timer.timeout.connect(self._verify_ptp_startup)
        
        # Connect to settings dirty signal
        if self.settings_tab:
            self.settings_tab.dirty_changed.connect(self._on_settings_dirty_changed)
        
        self.init_ui()
        self._load_saved_interface()
        
    def init_ui(self):
        scroll = QWidget()
        layout = QVBoxLayout(scroll)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Top: PTP Control Group ──────────────────────────────
        ptp_group = QGroupBox("PTP Clock Synchronization (statime)")
        ptp_layout = QVBoxLayout(ptp_group)
        ptp_layout.setSpacing(8)
        self.ptp_group = ptp_group
        self.ptp_layout = ptp_layout

        # Interface selection row
        iface_row = QHBoxLayout()
        iface_row.addWidget(QLabel("Interface:"))
        self.interface_combo = QComboBox()
        self.interface_combo.setMinimumWidth(200)
        self.interface_combo.setEnabled(True)
        iface_row.addWidget(self.interface_combo, 1)
        
        self.refresh_iface_btn = QPushButton("↻")
        self.refresh_iface_btn.setFixedWidth(36)
        self.refresh_iface_btn.setToolTip("Refresh interface list")
        self.refresh_iface_btn.clicked.connect(self._refresh_interfaces)
        iface_row.addWidget(self.refresh_iface_btn)
        
        self.ptp_v1_radio = QRadioButton("PTPv1")
        self.ptp_v1_radio.setToolTip("IEEE 1588-2002")
        self.ptp_v2_radio = QRadioButton("PTPv2")
        self.ptp_v2_radio.setToolTip("IEEE 1588-2008")
        self.ptp_v2_radio.setChecked(True)
        self.ptp_version_group = QButtonGroup(self)
        self.ptp_version_group.addButton(self.ptp_v1_radio, 1)
        self.ptp_version_group.addButton(self.ptp_v2_radio, 2)
        self.ptp_version_group.idToggled.connect(self._on_ptp_version_toggled)
        ptp_layout.addLayout(iface_row)

        # PTP version radios (own row: below interface, above start/stop)
        radio_row = QHBoxLayout()
        radio_row.addStretch()
        radio_row.addWidget(self.ptp_v1_radio)
        radio_row.addWidget(self.ptp_v2_radio)
        radio_row.addStretch()
        ptp_layout.addLayout(radio_row)

        # IP address display
        self.ip_label = QLabel("IP: —")
        self.ip_label.setStyleSheet("color: #aaa; font-size: 11px;")

        # Start/Stop buttons row
        btn_row = QHBoxLayout()
        
        self.start_ptp_btn = QPushButton("▶ Start")
        self.start_ptp_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                border: none; padding: 10px 20px;
                font-size: 14px; font-weight: bold; border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.start_ptp_btn.clicked.connect(self.start_ptp)
        btn_row.addWidget(self.start_ptp_btn)

        self.stop_ptp_btn = QPushButton("■ Stop")
        self.stop_ptp_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white;
                border: none; padding: 10px 20px;
                font-size: 14px; font-weight: bold; border-radius: 4px;
            }
            QPushButton:hover { background-color: #da190b; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.stop_ptp_btn.setEnabled(False)
        self.stop_ptp_btn.clicked.connect(self.stop_ptp)
        btn_row.addWidget(self.stop_ptp_btn)

        # Sync status indicator
        btn_row.addSpacing(16)
        btn_row.addWidget(QLabel("Sync:"))
        self.sync_light = QLabel()
        self.sync_light.setFixedSize(24, 24)
        self.sync_light.setStyleSheet("background-color: gray; border-radius: 12px;")
        btn_row.addWidget(self.sync_light)
        
        self.sync_label = QLabel("—")
        self.sync_label.setStyleSheet("color: #ccc; font-size: 12px; font-weight: bold;")
        self.sync_label.setMinimumWidth(140)
        btn_row.addWidget(self.sync_label)
        
        btn_row.addStretch()
        ptp_layout.addLayout(btn_row)

        # PTP Status details
        status_strip = QHBoxLayout()
        status_strip.setSpacing(16)
        self.ptp_state_label = QLabel("State: —")
        self.ptp_state_label.setStyleSheet("color: #ccc; font-size: 11px;")
        self.ptp_offset_label = QLabel("Offset: —")
        self.ptp_offset_label.setStyleSheet("color: #ccc; font-size: 11px;")
        self.ptp_freq_label = QLabel("Freq: —")
        self.ptp_freq_label.setStyleSheet("color: #ccc; font-size: 11px;")
        status_strip.addWidget(self.ip_label)
        status_strip.addStretch(1)
        status_strip.addWidget(self.ptp_state_label)
        status_strip.addStretch(1)
        status_strip.addWidget(self.ptp_offset_label)
        status_strip.addStretch(1)
        status_strip.addWidget(self.ptp_freq_label)
        ptp_layout.addLayout(status_strip)

        # ── Middle: Inferno ALSA Plugin Control ─────────────────
        inferno_group = QGroupBox("Inferno ALSA Plugin (Dante Virtual Soundcard)")
        inferno_layout = QVBoxLayout(inferno_group)
        inferno_layout.setSpacing(8)
        self.inferno_group = inferno_group

        # Tools group (NetAudio, qpwgraph, Cable – stacked vertically)
        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(6)

        self.netaudio_btn = QPushButton("🌐 Dante Routing - Open NetAudio Web UI")
        self.netaudio_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white;
                border: none; padding: 8px 14px;
                font-size: 12px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self.netaudio_btn.setEnabled(True)  # Always enabled
        self.netaudio_btn.clicked.connect(self._open_netaudio)
        tools_layout.addWidget(self.netaudio_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.qpwgraph_btn = QPushButton("PipeWire Routing - Open qpwgraph")
        try:
            from PyQt6.QtGui import QIcon
            _qpw_icon = QIcon("/usr/share/icons/hicolor/32x32/apps/org.rncbc.qpwgraph.png")
            if _qpw_icon.isNull():
                _qpw_icon = QIcon("/usr/share/icons/Numix-Circle/48/apps/org.rncbc.qpwgraph.svg")
            if not _qpw_icon.isNull():
                self.qpwgraph_btn.setIcon(_qpw_icon)
                self.qpwgraph_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.qpwgraph_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0; color: white;
                border: none; padding: 8px 14px;
                font-size: 12px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #7B1FA2; }
        """)
        self.qpwgraph_btn.clicked.connect(self._open_qpwgraph)
        tools_layout.addWidget(self.qpwgraph_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.cable_btn = QPushButton("PipeWire Settings - Open Cable")
        try:
            from PyQt6.QtGui import QIcon
            _cable_icon = QIcon("/usr/share/icons/hicolor/scalable/apps/jack-plug.svg")
            if _cable_icon.isNull():
                _cable_icon = QIcon("/usr/share/icons/hicolor/scalable/apps/jack-plug-dark.svg")
            if not _cable_icon.isNull():
                self.cable_btn.setIcon(_cable_icon)
                self.cable_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.cable_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800; color: white;
                border: none; padding: 8px 14px;
                font-size: 12px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #F57C00; }
        """)
        self.cable_btn.clicked.connect(self._open_cable)
        tools_layout.addWidget(self.cable_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # Equalize widths: all buttons as wide as the widest one
        _tools = (self.netaudio_btn, self.qpwgraph_btn, self.cable_btn)
        _max_w = max(b.sizeHint().width() for b in _tools)
        for _b in _tools:
            _b.setFixedWidth(_max_w)

        inferno_layout.addLayout(tools_layout)

        # Quick test button
        test_row = QHBoxLayout()
        self.test_alsa_btn = QPushButton("Test ALSA Device (aplay -L)")
        self.test_alsa_btn.setToolTip(
            "Note: The Inferno ALSA plugin activates automatically when an application\n"
            "opens the 'inferno' PCM device (via PipeWire). No separate start button needed.\n"
            "\n"
            "Click to run 'aplay -L' and check whether the inferno device is listed."
        )
        self.test_alsa_btn.clicked.connect(self._test_alsa_device)
        test_row.addWidget(self.test_alsa_btn)
        test_row.addStretch()
        inferno_layout.addLayout(test_row)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(ptp_group, 1, Qt.AlignmentFlag.AlignTop)
        top_row.addWidget(inferno_group, 1)
        layout.addLayout(top_row)

        # ── Bottom: Log Terminal ────────────────────────────────
        log_group = QGroupBox("Statime Log Output")
        log_layout = QVBoxLayout(log_group)

        # Header with verbose toggle
        log_header = QHBoxLayout()
        self.verbose_cb = QCheckBox("Verbose (fast summaries)")
        self.verbose_cb.setStyleSheet("font-size: 11px;")
        self.verbose_cb.toggled.connect(self._on_verbose_toggled)
        log_header.addWidget(self.verbose_cb)
        self.filtered_cb = QCheckBox("Filtered")
        self.filtered_cb.setStyleSheet("font-size: 11px;")
        self.filtered_cb.setChecked(True)
        log_header.addWidget(self.filtered_cb)
        log_header.addStretch()
        log_header.addWidget(QLabel("PTP Log:"))
        log_layout.addLayout(log_header)

        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont("JetBrains Mono, Courier New, monospace", 10))
        self.terminal_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.terminal_output.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d0d;
                color: #E0E0E0;
                border: 1px solid #333333;
                selection-background-color: #3d3d3d;
            }
        """)
        log_layout.addWidget(self.terminal_output)

        layout.addWidget(log_group, stretch=1)

        # Set as main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # Process setup
        self.ptp_process = QProcess()
        self.ptp_process.readyReadStandardOutput.connect(self._on_stdout)
        self.ptp_process.readyReadStandardError.connect(self._on_stderr)
        self.ptp_process.finished.connect(self._ptp_finished)

        # Update interface IP when selection changes
        self.interface_combo.currentIndexChanged.connect(self._on_interface_changed)

    def _load_saved_interface(self):
        """Load saved interface from settings."""
        self._refresh_interfaces()
        settings = QSettings("InfernoGUI", "control")
        saved = settings.value("selected_interface", "", type=str)
        ptp_ver = settings.value("ptp_version", "v2", type=str)
        
        if ptp_ver == 'v1':
            self.ptp_v1_radio.setChecked(True)
        else:
            self.ptp_v2_radio.setChecked(True)
        
        if saved:
            idx = self.interface_combo.findData(saved)
            if idx >= 0:
                self.interface_combo.setCurrentIndex(idx)
    
    def _refresh_interfaces(self):
        """Refresh the interface list."""
        current = self.interface_combo.currentData()
        self.interface_combo.clear()
        
        from inferno_gui.core.config import get_available_interfaces, get_interface_ip
        interfaces = get_available_interfaces()
        
        # Store IP info for each interface
        self._interface_ips = {}
        
        if interfaces:
            for iface in interfaces:
                ip = get_interface_ip(iface)
                self._interface_ips[iface] = ip
                display_text = f"{iface} ({ip})" if ip else f"{iface} (no IP)"
                self.interface_combo.addItem(display_text, iface)
            # Restore selection
            if current:
                idx = self.interface_combo.findData(current)
                if idx >= 0:
                    self.interface_combo.setCurrentIndex(idx)
        else:
            self.interface_combo.addItem("No interfaces found")
            self.interface_combo.setEnabled(False)
            self.start_ptp_btn.setEnabled(False)
        
        # Update start button state based on current selection
        self._update_start_button_state()
    
    def _update_start_button_state(self):
        """Enable start button only if selected interface has an IP."""
        iface = self.interface_combo.currentData()
        if iface and iface in self._interface_ips and self._interface_ips[iface]:
            self.start_ptp_btn.setEnabled(True)
        else:
            self.start_ptp_btn.setEnabled(False)
    
    def _on_interface_changed(self, index):
        """Handle interface selection change."""
        iface = self.interface_combo.currentData()
        if iface and not iface.startswith("No interfaces"):
            QSettings("InfernoGUI", "control").setValue("selected_interface", iface)
            ip = self._interface_ips.get(iface)
            if ip:
                self.ip_label.setText(f"IP: {ip}")
                self.ip_label.setStyleSheet("color: #4caf50; font-size: 11px;")
            else:
                self.ip_label.setText("IP: (no address assigned)")
                self.ip_label.setStyleSheet("color: #ffc107; font-size: 11px;")
            # Also update settings tab if linked
            if self.settings_tab:
                self.settings_tab.set_interface(iface)
            # Update start button state
            self._update_start_button_state()
    
    def _on_ptp_version_toggled(self, button_id: int, checked: bool):
        """Handle PTP version radio button change."""
        if checked:
            version = 'v1' if button_id == 1 else 'v2'
            QSettings("InfernoGUI", "control").setValue("ptp_version", version)
            if self.settings_tab:
                self.settings_tab.set_ptp_version(version)

    def start_ptp(self):
        """Start statime PTP daemon."""
        iface = self.interface_combo.currentData()
        if not iface or iface.startswith("No interfaces"):
            self._append_log("ERROR: Please select a valid network interface")
            return

        # Check sudo
        sudo_check = QProcess()
        sudo_check.start("sudo", ["-n", "true"])
        sudo_check.waitForFinished(3000)
        if sudo_check.exitCode() != 0:
            self._append_log("ERROR: No cached sudo credentials.")
            self._append_log("Run 'sudo -v' in a terminal first, then click START.")
            return

        # Determine config file
        ptp_version = 'v1' if self.ptp_v1_radio.isChecked() else 'v2'
        # Use ACTUAL_HOME for correct paths
        from inferno_gui.core.config import get_work_dir, get_default_statime_config, get_statime_binary
        statime_bin = get_statime_binary()
        config_file = get_default_statime_config(ptp_version)

        if not statime_bin.exists():
            self._append_log(f"ERROR: statime binary not found at {statime_bin}")
            self._append_log("Please run the installation script first.")
            return

        # Update config with selected interface
        self._update_statime_config(config_file, iface)

        self.parser.reset_all()
        self.terminal_output.clear()
        self._append_log(f"Starting statime (PTP{ptp_version[-1]}) on {iface}...")
        self._append_log(f"Config: {config_file}")
        self._append_log(f"Binary: {statime_bin}")

        cmd = f"sudo {statime_bin} -c {config_file}"
        
        # Create new QProcess if needed (after previous stop)
        if self.ptp_process is None:
            self.ptp_process = QProcess()
            self.ptp_process.readyReadStandardOutput.connect(self._on_stdout)
            self.ptp_process.readyReadStandardError.connect(self._on_stderr)
            self.ptp_process.finished.connect(self._ptp_finished)
        
        self.ptp_process.start("bash", ["-c", cmd])
        
        # Gate: PipeWire nodes only after a stable PTP lock
        # (v2: 1000 ns, v1: 1500 ns; 5 consecutive stable ticks, no timeout)
        threshold = 1500 if self.ptp_v1_radio.isChecked() else 1000
        self._lock_gate = LockGate(threshold, 5)
        self._awaiting_lock = True
        self._lock_wait_ticks = 0
        self._append_log(f"Waiting for PTP lock before creating PipeWire nodes... (threshold {threshold} ns)")
        
        # Set starting state - will be confirmed by _verify_ptp_startup after 2.5s
        self._ptp_starting = True
        self.start_ptp_btn.setEnabled(False)
        self.stop_ptp_btn.setEnabled(True)
        self.interface_combo.setEnabled(False)
        self.ptp_v1_radio.setEnabled(False)
        self.ptp_v2_radio.setEnabled(False)
        self.refresh_iface_btn.setEnabled(False)
        self._append_log("Waiting for PTP process to stabilize...")
        self._startup_verify_timer.start(2500)  # 2.5 seconds to verify startup

    def _verify_ptp_startup(self):
        """Verify PTP process started successfully after a short delay."""
        self._ptp_starting = False
        if self.ptp_process and self.ptp_process.state() == QProcess.ProcessState.Running:
            self.is_ptp_running = True
            self._update_timer.start()
            self.ptp_started.emit()
            self._emit_status()
            self._append_log("PTP process started successfully.")
        else:
            self._reset_ptp_state()
            self._append_log("ERROR: PTP process failed to start or exited immediately")

    def _update_statime_config(self, config_path: Path, interface: str):
        """Update statime config with selected interface."""
        from inferno_gui.core.config import StatimeConfig
        try:
            cfg = StatimeConfig(str(config_path))
            if cfg.load():
                cfg.set_interface(interface)
                cfg.save()
                self._append_log(f"Updated config with interface: {interface}")
        except Exception as e:
            self._append_log(f"Warning: Could not update config: {e}")

    def stop_ptp(self):
        """Stop statime PTP daemon."""
        # Verify-Timer sofort stoppen: sonst koennte er nach einem User-Stop
        # im 2,5-s-Startfenster noch "started successfully" loggen.
        self._startup_verify_timer.stop()
        # Gate-State bedingungslos aufraeumen: waehrend des 2,5-s-Startfensters
        # (_ptp_starting) ist is_ptp_running noch False - ein User-Stop darf
        # trotzdem _awaiting_lock/_lock_gate loeschen, sonst koennte ein
        # spaeteres _verify_ptp_startup doch noch Nodes erzeugen.
        self._awaiting_lock = False
        self._lock_gate = None
        # Auch waehrend des Startfensters (_ptp_starting, is_ptp_running noch
        # False) muss der Prozess terminiert werden - sonst laeuft statime
        # nach einem User-Stop weiter.
        if self.ptp_process and (self.is_ptp_running or self._ptp_starting):
            self._append_log("Stopping PTP...")
            self.ptp_process.terminate()
            if not self.ptp_process.waitForFinished(3000):
                self._append_log("PTP did not terminate gracefully, forcing...")
                self.ptp_process.kill()
                self.ptp_process.waitForFinished()
            self._reset_ptp_state()
            self._append_log("PTP stopped.")
        
        # Destroy PipeWire nodes for Inferno
        self._destroy_pipewire_nodes()

        # Kein _emit_status() hier: _ptp_finished emittiert bereits synchron
        # beim process-finished in waitForFinished - doppelter Emit vermeiden.
        self.ptp_stopped.emit()

    def _create_pipewire_nodes(self):
        """Create PipeWire nodes for Inferno sink and source."""
        self._append_log("Creating PipeWire nodes for Inferno...")
        
        # Create sink node directly
        sink_cmd = [
            "pw-cli", "create-node", "adapter",
            'object.linger=1',
            'factory.name=api.alsa.pcm.sink',
            'node.name=Inferno_sink',
            'media.class=Audio/Sink',
            'api.alsa.path=inferno',
            'session.suspend-timeout-seconds=0',
            'node.pause-on-idle=false',
            'node.suspend-on-idle=false',
            'node.always-process=true',
            'api.alsa.headroom=128',
            'api.alsa.pcm.card=999'
        ]
        
        # Create source node directly
        source_cmd = [
            "pw-cli", "create-node", "adapter",
            'object.linger=1',
            'factory.name=api.alsa.pcm.source',
            'node.name=Inferno_source',
            'media.class=Audio/Source',
            'api.alsa.path=inferno',
            'session.suspend-timeout-seconds=0',
            'node.pause-on-idle=false',
            'node.suspend-on-idle=false',
            'node.always-process=true',
            'api.alsa.headroom=128',
            'api.alsa.pcm.card=999'
        ]
        
        import re

        for name, node_name, cmd in [("Inferno sink", "Inferno_sink", sink_cmd),
                                     ("Inferno source", "Inferno_source", source_cmd)]:
            proc = QProcess()
            proc.setProcessEnvironment(_get_pipewire_env())
            proc.start(cmd[0], cmd[1:])  # Start without bash -c

            timed_out = not proc.waitForFinished(10000)
            if timed_out:
                # Prozess sauber beenden statt die lokale Instanz laufend
                # verfallen zu lassen; NIEMALS Erfolg behaupten.
                proc.kill()
                proc.waitForFinished(1000)
                self._append_log(f"{name} creation FAILED: timed out after 10 s")
                continue

            exit_code = proc.exitCode()
            stderr_text = bytes(proc.readAllStandardError()).decode(
                'utf-8', errors='replace').strip()

            # Fail fast bei non-zero Exit - niemals Erfolg ohne Pruefung loggen.
            if exit_code != 0:
                detail = f"exit code {exit_code}"
                if stderr_text:
                    detail += f"; stderr: {stderr_text}"
                self._append_log(f"{name} creation FAILED: {detail}")
                continue

            # Auch bei Exit 0 ist ein "error" im create-stderr ein Scheitern
            # (pw-cli meldet teils Fehler nur auf stderr, nicht per Exit-Code).
            if 'error' in stderr_text.lower():
                self._append_log(
                    f"{name} creation FAILED: stderr: {stderr_text}")
                continue

            # Ehrliche Verifikation: die Node muss jetzt wirklich existieren.
            # Der PipeWire-Daemon blockiert nach create-node bis zu ~13 s
            # (der neue Node wartet auf Clock) und beantwortet in diesem
            # Fenster keine Registry-Abfragen - ein einzelner pw-cli-Aufruf
            # liefert daher garantiert False-Negatives. Deshalb bedingt
            # warten: bis zu 8 Versuche / ~15 s Budget, 0,5 s Pause nach
            # jedem erfolglosen Versuch, sofortiger Abbruch bei Erfolg.
            deadline = time.monotonic() + 15.0
            verified = False
            # Letzter bekannter Misserfolgsgrund (timeout/exception/error/missing).
            last_failure = ("timeout", None)
            for _attempt in range(8):
                if time.monotonic() >= deadline:
                    break
                try:
                    check = subprocess.run(['pw-cli', 'ls', 'Node'],
                                           capture_output=True, text=True,
                                           timeout=2, env=_get_pipewire_env())
                except subprocess.TimeoutExpired:
                    last_failure = ("timeout", None)
                except (OSError, subprocess.SubprocessError) as e:
                    last_failure = ("exception", e)
                else:
                    node_present = re.search(
                        rf'node\.name\s*=\s*"{re.escape(node_name)}"',
                        check.stdout)
                    combined = (check.stdout + check.stderr).lower()
                    if node_present and 'error' not in combined:
                        verified = True
                        break
                    if 'error' in combined:
                        last_failure = ("error", None)
                    else:
                        last_failure = ("missing", node_name)
                time.sleep(0.5)

            if verified:
                output = bytes(proc.readAllStandardOutput()).decode(
                    'utf-8', errors='replace').strip()
                if output:
                    self._append_log(f"{name} created: {output}")
                self._append_log(f"{name} created successfully (verified)")
            else:
                kind, detail = last_failure
                if kind == "timeout":
                    self._append_log(
                        f"{name} creation FAILED: verification timed out")
                elif kind == "exception":
                    self._append_log(
                        f"{name} creation FAILED: verification could "
                        f"not run ({detail})")
                elif kind == "error":
                    self._append_log(
                        f"{name} creation FAILED: pw-cli reported an error "
                        "while listing nodes")
                else:
                    self._append_log(
                        f'{name} creation FAILED: node "{node_name}" not '
                        "found in PipeWire after creation")

    def _destroy_pipewire_nodes(self):
        """Destroy PipeWire nodes for Inferno sink and source."""
        self._append_log("Destroying PipeWire nodes for Inferno...")
        
        # Simple, robust approach using subprocess
        import subprocess
        import re
        
        try:
            # Use shell command for reliable node listing
            result = subprocess.run(['pw-cli', 'ls', 'Node'], 
                                   capture_output=True, text=True, timeout=5, env=_get_pipewire_env())
            output = result.stdout
            
            if output:
                self._append_log("--- PipeWire Nodes ---")
                self._append_log(output)
                self._append_log("--------------------")
                
                # Simple approach: Look for any node with 'inferno' in name
                # More flexible pattern that matches various formats
                inferno_pattern = re.compile(r'inferno', re.IGNORECASE)
                
                # Also look for node IDs (simpler approach)
                node_id_pattern = re.compile(r'id\s+(\d+)')
                node_ids = node_id_pattern.findall(output)
                
                # Look for node names with 'inferno'
                node_name_pattern = re.compile(r'node\.name\s*=\s*"([^"]+)"')
                node_names = node_name_pattern.findall(output)
                
                # Combine and find Inferno nodes
                inferno_nodes = []
                for i, node_name in enumerate(node_names):
                    if 'inferno' in node_name.lower():
                        node_id = node_ids[i] if i < len(node_ids) else 'unknown'
                        inferno_nodes.append((node_id, node_name))
                
                if inferno_nodes:
                    self._append_log(f"Found {len(inferno_nodes)} Inferno nodes to destroy:")
                    for node_id, node_name in inferno_nodes:
                        self._append_log(f"  - {node_name} (ID: {node_id})")
                    
                    # Destroy nodes
                    for node_id, node_name in inferno_nodes:
                        destroy_proc = subprocess.run(
                            ['pw-cli', 'destroy', node_id],
                            capture_output=True, text=True, timeout=3, env=_get_pipewire_env()
                        )
                        if destroy_proc.returncode == 0:
                            self._append_log(f"Destroyed {node_name} (ID: {node_id})")
                        else:
                            self._append_log(f"Warning: Failed to destroy {node_name} (ID: {node_id})")
                            if destroy_proc.stderr:
                                self._append_log(f"  Error: {destroy_proc.stderr.strip()}")
                else:
                    self._append_log("No Inferno PipeWire nodes found to destroy")
            else:
                self._append_log("No PipeWire output available")
                
        except subprocess.TimeoutExpired:
            self._append_log("Warning: pw-cli ls Node command timed out")
        except Exception as e:
            self._append_log(f"Warning: Error destroying nodes: {e}")

    def _reset_ptp_state(self):
        self.is_ptp_running = False
        self._ptp_starting = False
        self._lock_gate = None
        self._awaiting_lock = False
        self._lock_wait_ticks = 0
        self.ptp_process = None
        # Unvollstaendige Zeilen-Reste verwerfen - ein halbes Fragment
        # am Laufende ist nicht informativ und wuerde die erste Zeile
        # des naechsten Laufs korruptieren.
        self._stdout_buffer = ''
        self._stderr_buffer = ''
        self.start_ptp_btn.setEnabled(True)
        self.stop_ptp_btn.setEnabled(False)
        self.interface_combo.setEnabled(True)
        self.ptp_v1_radio.setEnabled(True)
        self.ptp_v2_radio.setEnabled(True)
        self.refresh_iface_btn.setEnabled(True)
        self._update_timer.stop()
        self._startup_verify_timer.stop()
        self._ptp_state = ""
        self._ptp_offset = None
        self._ptp_freq = None
        self.sync_light.setStyleSheet("background-color: gray; border-radius: 12px;")
        self.sync_label.setText("—")
        self.ptp_state_label.setText("State: —")
        self.ptp_offset_label.setText("Offset: —")
        self.ptp_freq_label.setText("Freq: —")

    def _ptp_finished(self, exit_code, exit_status):
        was_running = self.is_ptp_running
        missed_lock = self._awaiting_lock
        self._reset_ptp_state()
        # Status emittieren: auch bei Prozess-Tod von selbst muss das Icon
        # im MainWindow zurueck auf schwarz/weiß wechseln (Merker macht den
        # Emit ohne Lock-Wechsel harmlos).
        self._emit_status()
        if was_running:
            if exit_code == 0:
                self._append_log("PTP process completed successfully.")
            else:
                self._append_log(f"PTP process exited with code: {exit_code}")
            if missed_lock:
                self._append_log("PTP exited before lock - no PipeWire nodes created")
            self.ptp_stopped.emit()
        else:
            # Process failed during startup - _verify_ptp_startup already logged error
            if missed_lock:
                self._append_log("PTP exited before lock - no PipeWire nodes created")
            if exit_code != 0:
                self._append_log(f"PTP process exited during startup with code: {exit_code}")

    def _on_stdout(self):
        data = self.ptp_process.readAllStandardOutput()
        text = bytes(data).decode('utf-8', errors='replace')
        self._stdout_buffer += text
        if not self._write_timer.isActive():
            self._write_timer.start()

    def _on_stderr(self):
        data = self.ptp_process.readAllStandardError()
        text = bytes(data).decode('utf-8', errors='replace')
        self._stderr_buffer += text
        if not self._write_timer.isActive():
            self._write_timer.start()

    def _flush_terminal(self):
        for attr in ('_stdout_buffer', '_stderr_buffer'):
            buffer = getattr(self, attr)
            if not buffer:
                continue
            # Nur komplette Zeilen (bis einschliesslich letztem '\n') an den
            # Parser geben; ein unvollstaendiger Rest bleibt im Puffer und
            # wird erst beim naechsten Flush (oder forciert ueber 8192
            # Zeichen) verarbeitet - sonst zerstoeren 50-ms-Chunk-Grenzen
            # die Werte.
            end = buffer.rfind('\n')
            if end == -1:
                if len(buffer) > _MAX_RESIDUE:
                    self._process_log_output(buffer)
                    setattr(self, attr, '')
                continue
            self._process_log_output(buffer[:end + 1])
            setattr(self, attr, buffer[end + 1:])
        self._write_timer.stop()

    def _process_log_output(self, text: str):
        """Process log output through parser and display results.

        The parser runs on every line in both modes (metrics/status keep
        updating); the Filtered checkbox only controls what is displayed.
        """
        raw = not self.filtered_cb.isChecked()
        # ANSI-Sequenzen hier strippen - NICHT schon beim Empfang in
        # _on_stdout/_on_stderr: dort kann eine Escape-Sequenz ueber zwei
        # 50-ms-Chunks gesplittet sein (\x1b[3 + 5m) und wuerde als Fragment
        # nie gematcht. _flush_terminal liefert nur komplette Zeilen, ueber
        # die eine Escape-Sequenz nicht ueberspannen kann.
        text = _ANSI_CSI_RE.sub('', text)
        for line in text.split('\n'):
            if not line:
                continue
            entry = self.parser.parse_line(line)
            if raw:
                # Raw mode: show the line verbatim (no [:200] truncation).
                self._append_colored(
                    line, entry.severity if entry else LogSeverity.INFO)
            elif entry:
                # update_pending_metrics is now called internally by parse_line
                formatted = format_log_entry(entry)
                self._append_colored(formatted, entry.severity)

    def _append_colored(self, text: str, severity: LogSeverity):
        """Append text with color coding."""
        cursor = self.terminal_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        
        color_map = {
            LogSeverity.ERROR: QColor('#f44336'),
            LogSeverity.WARNING: QColor('#ffc107'),
            LogSeverity.INFO: QColor('#E0E0E0'),
        }
        
        from PyQt6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(color_map.get(severity, color_map[LogSeverity.INFO]))
        cursor.insertText(text + '\n', fmt)
        self.terminal_output.setTextCursor(cursor)
        self.terminal_output.ensureCursorVisible()
        _trim_terminal(self.terminal_output)

    def _append_log(self, text: str):
        """Append plain log message."""
        self._append_colored(f"[{time.strftime('%H:%M:%S')}] {text}", LogSeverity.INFO)

    def _update_status_panel(self):
        """Update status indicators from parser."""
        status = self.parser.get_sync_status()

        # Anzeige-Metriken: Im gefilterten Modus koppeln Offset/Freq an die
        # letzte angezeigte Summary-Zeile (Log = Single Source of Truth) -
        # die Pending-Metriken laufen bei jeder Zeile mit und waeren der
        # Anzeige voraus. Noch keine Summary erzeugt -> None ("—"). Im
        # Rohmodus wird jede Zeile angezeigt, dort sind die Live-Werte
        # identisch mit dem Log.
        if self.filtered_cb.isChecked():
            summary = self.parser.get_last_summary()
            if summary is not None:
                display_offset = summary.offset_ns
                display_freq = summary.freq_ppb
            else:
                # Noch keine Summary angezeigt: Rueckfall auf die Live-
                # Werte, damit das Panel nicht leer bleibt, wenn der Parser
                # bereits Metriken kennt (im Realbetrieb erzeugt die erste
                # Metrik-Zeile sofort eine Summary).
                display_offset = status['offset_ns']
                display_freq = status['freq_ppb']
        else:
            display_offset = status['offset_ns']
            display_freq = status['freq_ppb']

        # Lock-Gate: PipeWire nodes only after 5 consecutive stable ticks
        # in the target state (display logic below stays separate).
        if self._awaiting_lock and self.is_ptp_running and self._lock_gate is not None:
            if self._lock_gate.feed(status['state'], status['offset_ns']):
                self._awaiting_lock = False
                self._append_log(
                    f"PTP locked (offset {status['offset_ns']} ns, 5/5 ticks) - creating PipeWire nodes..."
                )
                self._create_pipewire_nodes()
            else:
                self._lock_wait_ticks += 1
                if self._lock_wait_ticks >= 20:
                    self._append_log(
                        f"still waiting for lock: state={status['state']}, offset={status['offset_ns']} ns"
                    )
                    self._lock_wait_ticks = 0

        self._ptp_state = status['state']
        self._ptp_offset = display_offset
        self._ptp_freq = display_freq
        
        # Update labels - show sync quality based on offset
        state = status['state']
        offset = status['offset_ns']
        if state == 'SLAVE' and offset is not None:
            if abs(offset) <= 200:
                display_state = "Locked"
            elif abs(offset) <= 1000:
                display_state = "Syncing..."
            else:
                display_state = "SLAVE"
        else:
            display_state = state
        self.ptp_state_label.setText(f"State: {display_state}")
        
        if display_offset is not None:
            self.ptp_offset_label.setText(f"Offset: {display_offset} ns")
        else:
            self.ptp_offset_label.setText("Offset: —")
        
        if display_freq is not None:
            self.ptp_freq_label.setText(f"Freq: {display_freq} ppb")
        else:
            self.ptp_freq_label.setText("Freq: —")
        
        # Update sync light (Schwellen nutzen die Anzeige-Metriken; State
        # und Lock-Gate oben bleiben live)
        light_status = dict(status)
        light_status['offset_ns'] = display_offset
        self._update_sync_light(light_status)
        
        # Emit for session tab
        self._emit_status()

    def _update_sync_light(self, status: dict):
        """Update the sync traffic light."""
        state = status['state']
        offset = status['offset_ns']
        
        if state == 'MASTER':
            color = "#2196F3"
            label = "Grand Master"
            tip = "Grand Master – no PTP peer detected"
        elif state == 'FAULTY':
            color = "#f44336"
            label = "FAULTY"
            tip = "FAULTY – link or PTP error"
        elif state == 'LISTENING':
            color = "gray"
            label = "Listening..."
            tip = "Listening for PTP messages..."
        elif state == 'UNCALIBRATED':
            color = "orange"
            label = "Uncalibrated"
            tip = "Uncalibrated – acquiring sync"
        elif state == 'SLAVE' and offset is not None:
            if abs(offset) <= 200:
                color = "#4caf50"
                label = f"Locked ({abs(offset)} ns)"
                tip = f"Sync: {offset}ns (excellent)"
            elif abs(offset) <= 1000:
                color = "#ffc107"
                label = f"Syncing... ({abs(offset)} ns)"
                tip = f"Sync: {offset}ns (good)"
            else:
                color = "#f44336"
                label = f"SLAVE ({abs(offset)} ns)"
                tip = f"Sync: {offset}ns (poor)"
        else:
            color = "gray"
            label = "Initializing..."
            tip = "Waiting for sync..."
        
        self.sync_light.setStyleSheet(f"background-color: {color}; border-radius: 12px;")
        self.sync_light.setToolTip(tip)
        self.sync_label.setText(label)

    def _emit_status(self):
        """Emit status for session tab."""
        self.status_changed.emit({
            'ptp_running': self.is_ptp_running,
            'ptp_state': self._ptp_state,
            'ptp_offset': self._ptp_offset,
            'ptp_freq': self._ptp_freq,
        })

    def _on_verbose_toggled(self, checked: bool):
        """Handle verbose checkbox toggle."""
        self.parser.filter_interval = 0.1 if checked else 1.0
        if checked:
            self._append_log("Verbose mode enabled - showing summaries 10x/sec")
        else:
            self._append_log("Verbose mode disabled - filtered output (1 line/sec)")

    def _test_alsa_device(self):
        """Test if inferno ALSA device is available."""
        import subprocess
        import os
        try:
            # Run as actual user so ~/.asoundrc is read correctly
            sudo_user = os.environ.get('SUDO_USER', 'jacob')
            result = subprocess.run(
                ['sudo', '-u', sudo_user, 'aplay', '-L'],
                capture_output=True, text=True, timeout=5
            )
            lines = [l for l in result.stdout.split('\n') if 'inferno' in l.lower()]
            if lines:
                self._append_log("Inferno ALSA device found:")
                for l in lines:
                    self._append_log(f"  {l.strip()}")
            else:
                self._append_log("Inferno ALSA device NOT found in aplay -L")
                self._append_log("Check ~/.asoundrc and ALSA plugin installation")
        except Exception as e:
            self._append_log(f"Error testing ALSA: {e}")

    def _open_qpwgraph(self):
        """Open qpwgraph."""
        try:
            subprocess.Popen(['qpwgraph'])
        except FileNotFoundError:
            try:
                subprocess.Popen(['flatpak', 'run', 'org.freedesktop.qpwgraph'])
            except Exception as e:
                self._append_log(f"Error opening qpwgraph: {e}")

    def _open_cable(self):
        """Open Cable."""
        try:
            subprocess.Popen(['cable'])
        except FileNotFoundError:
            try:
                subprocess.Popen(['flatpak', 'run', 'com.github.cable'])
            except Exception as e:
                self._append_log(f"Error opening Cable: {e}")

    def _open_netaudio(self):
        """Open netaudio web interface (auto-starts the daemon if needed)."""
        import subprocess
        import os
        # Get actual user (not root) to run netaudio command
        sudo_user = os.environ.get('SUDO_USER', 'jacob')
        # Use full path to netaudio (installed via pipx for the user)
        netaudio_path = f"/home/{sudo_user}/.local/bin/netaudio"
        base = ['sudo', '-u', sudo_user, netaudio_path]
        try:
            # Start daemon if not running ("already running" exits 0)
            r = subprocess.run(base + ['daemon', 'start'],
                               capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                self._append_log(f"netaudio daemon start failed: {(r.stderr or r.stdout).strip()}")
                return
            r = subprocess.run(base + ['daemon', 'web', '--open'],
                               capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                self._append_log(f"netaudio web open failed: {(r.stderr or r.stdout).strip()}")
        except subprocess.TimeoutExpired:
            self._append_log("netaudio command timed out")
        except FileNotFoundError:
            self._append_log("netaudio command not found - install netaudio first")
        except Exception as e:
            self._append_log(f"Error opening NetAudio Web UI: {e}")

    def get_ptp_status(self) -> dict:
        """Get current PTP status for session tab."""
        return {
            'running': self.is_ptp_running,
            'state': self._ptp_state,
            'offset': self._ptp_offset,
            'freq': self._ptp_freq,
        }

    def set_interface(self, iface: str):
        """Set interface from settings tab."""
        idx = self.interface_combo.findData(iface)
        if idx >= 0:
            self.interface_combo.setCurrentIndex(idx)

    def set_ptp_version(self, version: str):
        """Set PTP version from settings tab."""
        if version == 'v1':
            self.ptp_v1_radio.setChecked(True)
        else:
            self.ptp_v2_radio.setChecked(True)

    def is_running(self) -> bool:
        return self.is_ptp_running

    def get_interface(self) -> str:
        return self.interface_combo.currentData() or ""

    def get_ptp_version(self) -> str:
        return 'v1' if self.ptp_v1_radio.isChecked() else 'v2'

    def _log_all_pipewire_nodes(self):
        """Log all PipeWire nodes for debugging purposes."""
        self._append_log("=== ALL PipeWire Nodes ===")
        
        proc = QProcess()
        proc.setProcessEnvironment(_get_pipewire_env())
        proc.start("pw-cli", ["ls", "Node"])
        if proc.waitForFinished(5000):
            output = bytes(proc.readAllStandardOutput()).decode('utf-8', errors='replace')
            self._append_log(output)
            self._append_log("=========================")
            
            # Check for any nodes with "inferno" in the name (case insensitive)
            import re
            inferno_pattern = re.compile(r'inferno', re.IGNORECASE)
            if inferno_pattern.search(output):
                self._append_log("FOUND: Nodes containing 'inferno' in name")
            else:
                self._append_log("NOTE: No nodes with 'inferno' found in current list")
        else:
            self._append_log("Failed to get PipeWire nodes list for logging")

# Need QTextEdit import
from PyQt6.QtWidgets import QTextEdit