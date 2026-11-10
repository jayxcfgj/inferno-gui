"""Settings Tab – Configure Inferno audio parameters and system settings."""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QLineEdit,
    QCheckBox, QScrollArea, QMessageBox, QGridLayout, QStyle,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtCore import QUrl, QTimer

from inferno_gui.core.config import (
    InfernoConfig,
    StatimeConfig,
    get_available_interfaces,
    get_interface_ip,
    get_default_statime_config,
    get_work_dir,
)
from inferno_gui.core.log_parser import LogSeverity


class SettingsTab(QWidget):
    """Settings tab for configuring Inferno and statime."""
    
    # Signals
    settings_changed = pyqtSignal()
    interface_changed = pyqtSignal(str)
    ptp_version_changed = pyqtSignal(str)
    dirty_changed = pyqtSignal(bool)  # True when unsaved changes exist
    
    def __init__(self, control_tab=None):
        super().__init__()
        self.control_tab = control_tab
        self.inferno_config = InfernoConfig()
        self._dirty = False
        self._original_values = {}
        self._init_ui()
        self.load_settings()
        self._capture_original_values()
        self._setup_dirty_tracking()
    
    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Network Interface ────────────────────────────────────
        net_group = QGroupBox("Network Interface")
        net_layout = QFormLayout(net_group)
        net_layout.setSpacing(8)
        net_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.iface_combo = QComboBox()
        self.iface_combo.setMinimumWidth(250)
        self.iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        net_layout.addRow("Dante/PTP Interface:", self.iface_combo)

        self.refresh_iface_btn = QPushButton("↻ Refresh")
        self.refresh_iface_btn.setFixedWidth(100)
        self.refresh_iface_btn.clicked.connect(self._refresh_interfaces)
        net_layout.addRow("", self.refresh_iface_btn)

        self.ip_display = QLabel("—")
        self.ip_display.setStyleSheet("color: #4caf50; font-family: monospace;")
        net_layout.addRow("Current IP:", self.ip_display)

        # PTP Version
        self.ptp_v1_radio = QRadioButton("PTPv1 (IEEE 1588-2002)")
        self.ptp_v2_radio = QRadioButton("PTPv2 (IEEE 1588-2008)")
        self.ptp_v2_radio.setChecked(True)
        self.ptp_version_group = QButtonGroup(self)
        self.ptp_version_group.addButton(self.ptp_v1_radio, 1)
        self.ptp_version_group.addButton(self.ptp_v2_radio, 2)
        self.ptp_version_group.idToggled.connect(self._on_ptp_version_toggled)
        ptp_ver_layout = QHBoxLayout()
        ptp_ver_layout.addWidget(self.ptp_v1_radio)
        ptp_ver_layout.addWidget(self.ptp_v2_radio)
        ptp_ver_layout.addStretch()
        net_layout.addRow("PTP Version:", ptp_ver_layout)

        layout.addWidget(net_group)

        # ── Audio Parameters ─────────────────────────────────────
        audio_group = QGroupBox("Audio Parameters")
        audio_layout = QFormLayout(audio_group)
        audio_layout.setSpacing(8)
        audio_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.device_name = QLineEdit("Inferno")
        self.device_name.setMinimumWidth(250)
        audio_layout.addRow("Device Name:", self.device_name)

        self.sample_rate = QComboBox()
        for rate in [44100, 48000, 88200, 96000, 176400, 192000]:
            self.sample_rate.addItem(f"{rate} Hz", rate)
        self.sample_rate.setCurrentText("48000 Hz")
        audio_layout.addRow("Sample Rate:", self.sample_rate)

        self.tx_channels = QSpinBox()
        self.tx_channels.setRange(1, 64)
        self.tx_channels.setValue(24)
        self.tx_channels.setSuffix(" channels")
        audio_layout.addRow("TX Channels (Output):", self.tx_channels)

        self.rx_channels = QSpinBox()
        self.rx_channels.setRange(1, 64)
        self.rx_channels.setValue(24)
        self.rx_channels.setSuffix(" channels")
        audio_layout.addRow("RX Channels (Input):", self.rx_channels)

        layout.addWidget(audio_group)

        # ── Advanced statime Options ────────────────────────────
        adv_group = QGroupBox("Advanced statime Options")
        adv_layout = QFormLayout(adv_group)
        adv_layout.setSpacing(8)
        adv_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ptp_domain = QSpinBox()
        self.ptp_domain.setRange(0, 255)
        self.ptp_domain.setValue(0)
        adv_layout.addRow("PTP Domain:", self.ptp_domain)

        self.sync_interval = QSpinBox()
        self.sync_interval.setRange(-7, 7)
        self.sync_interval.setValue(0)
        self.sync_interval.setSuffix(" (log2 seconds)")
        adv_layout.addRow("Sync Interval:", self.sync_interval)

        self.announce_interval = QSpinBox()
        self.announce_interval.setRange(-7, 7)
        self.announce_interval.setValue(1)
        self.announce_interval.setSuffix(" (log2 seconds)")
        adv_layout.addRow("Announce Interval:", self.announce_interval)

        self.log_level = QComboBox()
        for level in ["ERROR", "WARN", "INFO", "DEBUG", "TRACE"]:
            self.log_level.addItem(level)
        self.log_level.setCurrentText("INFO")
        adv_layout.addRow("Log Level:", self.log_level)

        layout.addWidget(adv_group)

        # ── Config Files ────────────────────────────────────────
        config_group = QGroupBox("Config Files")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(8)

        # PipeWire override
        pw_override_path = Path.home() / ".config/systemd/user/pipewire.service.d/override.conf"
        self.pw_override_btn = QPushButton("Open PipeWire Override")
        try:
            from PyQt6.QtGui import QIcon
            _cfg_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _cfg_icon.isNull():
                self.pw_override_btn.setIcon(_cfg_icon)
                self.pw_override_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.pw_override_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(pw_override_path)))
        )
        config_layout.addWidget(self.pw_override_btn)
        
        self.pw_override_status = QLabel("Checking...")
        self.pw_override_status.setStyleSheet("color: #aaa; font-size: 11px;")
        config_layout.addWidget(self.pw_override_status)
        
        # PTPv1 config
        ptpv1_path = get_default_statime_config('v1')
        self.ptpv1_btn = QPushButton("Open PTPv1 Config")
        try:
            from PyQt6.QtGui import QIcon
            _cfg_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _cfg_icon.isNull():
                self.ptpv1_btn.setIcon(_cfg_icon)
                self.ptpv1_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.ptpv1_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ptpv1_path)))
        )
        config_layout.addWidget(self.ptpv1_btn)
        
        # PTPv2 config
        ptpv2_path = get_default_statime_config('v2')
        self.ptpv2_btn = QPushButton("Open PTPv2 Config")
        try:
            from PyQt6.QtGui import QIcon
            _cfg_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _cfg_icon.isNull():
                self.ptpv2_btn.setIcon(_cfg_icon)
                self.ptpv2_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.ptpv2_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ptpv2_path)))
        )
        config_layout.addWidget(self.ptpv2_btn)
        
        # ALSA config
        # Use a robust approach to get the actual user's home directory
        try:
            import pwd
            user_home = pwd.getpwnam(os.getlogin()).pw_dir
        except Exception:
            import os
            user = os.environ.get('SUDO_USER') or os.environ.get('USER') or os.environ.get('LOGNAME') or os.getlogin()
            user_home = Path(f"/home/{user}") if user != 'root' else Path.home()
        else:
            user_home = Path.home()
        alsa_rc_path = Path(user_home) / ".asoundrc"
        self.asoundrc_btn = QPushButton("Open ~/.asoundrc")
        try:
            from PyQt6.QtGui import QIcon
            _rc_icon = QIcon("/usr/share/icons/Papirus/24x24/mimetypes/text-x-generic.svg")
            if not _rc_icon.isNull():
                self.asoundrc_btn.setIcon(_rc_icon)
                self.asoundrc_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.asoundrc_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(alsa_rc_path)))
        )
        config_layout.addWidget(self.asoundrc_btn)
        
        self.alsa_plugin_status = QLabel("Checking...")
        self.alsa_plugin_status.setStyleSheet("color: #aaa; font-size: 11px;")
        config_layout.addWidget(self.alsa_plugin_status)

        layout.addWidget(config_group)

        # ── Actions ──────────────────────────────────────────────
        actions_group = QGroupBox("Actions")
        actions_layout = QHBoxLayout(actions_group)

        self.save_btn = QPushButton("💾 Save Configuration")
        self.save_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border: none;
                          padding: 10px 20px; font-size: 13px; font-weight: bold;
                          border-radius: 4px; }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.save_btn.clicked.connect(self.save_settings)
        actions_layout.addWidget(self.save_btn)

        self.reset_btn = QPushButton("🔄 Reset to Defaults")
        self.reset_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; border: none;
                          padding: 10px 20px; font-size: 13px; border-radius: 4px; }
            QPushButton:hover { background-color: #F57C00; }
        """)
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        actions_layout.addWidget(self.reset_btn)

        actions_layout.addStretch()
        layout.addWidget(actions_group)

        layout.addStretch()

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # Initial checks
        QTimer.singleShot(500, self._check_system_status)
    
    def _refresh_interfaces(self):
        """Refresh interface list."""
        current = self.iface_combo.currentData()
        self.iface_combo.clear()
        interfaces = get_available_interfaces()
        
        # Store IP info for each interface
        self._interface_ips = {}
        
        if interfaces:
            for iface in interfaces:
                ip = get_interface_ip(iface)
                self._interface_ips[iface] = ip
                display_text = f"{iface} ({ip})" if ip else f"{iface} (no IP)"
                self.iface_combo.addItem(display_text, iface)
            if current:
                idx = self.iface_combo.findData(current)
                if idx >= 0:
                    self.iface_combo.setCurrentIndex(idx)
        self._update_ip_display()
    
    def _on_iface_changed(self, index):
        """Handle interface change."""
        self._update_ip_display()
        iface = self.iface_combo.currentData()
        if iface:
            self.interface_changed.emit(iface)
    
    def _on_ptp_version_toggled(self, button_id: int, checked: bool):
        """Handle PTP version radio button change."""
        if checked:
            version = 'v1' if button_id == 1 else 'v2'
            self.ptp_version_changed.emit(version)

    def _update_ip_display(self):
        """Update IP address display for selected interface."""
        iface = self.iface_combo.currentData()
        if iface:
            ip = get_interface_ip(iface)
            if ip:
                self.ip_display.setText(ip)
                self.ip_display.setStyleSheet("color: #4caf50; font-family: monospace;")
                # Auto-fill bind IP if empty
            else:
                self.ip_display.setText("(no IP assigned)")
                self.ip_display.setStyleSheet("color: #ffc107; font-family: monospace;")
        else:
            self.ip_display.setText("—")
            self.ip_display.setStyleSheet("color: #aaa;")

    def _check_system_status(self):
        """Check PipeWire override and ALSA plugin status."""
        # Check PipeWire override
        override_file = Path.home() / ".config/systemd/user/pipewire.service.d/override.conf"
        if override_file.exists():
            content = override_file.read_text()
            if "@clock" in content:
                self.pw_override_status.setText("✓ Configured correctly")
                self.pw_override_status.setStyleSheet("color: #4caf50; font-size: 11px;")
            else:
                self.pw_override_status.setText("⚠ File exists but missing @clock filter")
                self.pw_override_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        else:
            self.pw_override_status.setText("✗ Not configured")
            self.pw_override_status.setStyleSheet("color: #f44336; font-size: 11px;")

        # Check ALSA plugin
        from inferno_gui.core.config import get_inferno_plugin, get_work_dir
        plugin_src = get_inferno_plugin()
        plugin_dst = Path("/usr/lib/x86_64-linux-gnu/alsa-lib/libasound_module_pcm_inferno.so")
        
        if plugin_dst.exists() or plugin_dst.is_symlink():
            try:
                target = plugin_dst.resolve()
                if target == plugin_src.resolve():
                    self.alsa_plugin_status.setText(f"✓ Installed and linked to {plugin_src}")
                    self.alsa_plugin_status.setStyleSheet("color: #4caf50; font-size: 11px;")
                else:
                    self.alsa_plugin_status.setText(f"⚠ Linked to different file: {target}")
                    self.alsa_plugin_status.setStyleSheet("color: #ffc107; font-size: 11px;")
            except Exception:
                self.alsa_plugin_status.setText("⚠ Symlink exists but target unclear")
                self.alsa_plugin_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        elif plugin_src.exists():
            self.alsa_plugin_status.setText(f"⚠ Built but not installed (run install script)")
            self.alsa_plugin_status.setStyleSheet("color: #ffc107; font-size: 11px;")
        else:
            self.alsa_plugin_status.setText("✗ Not built (run installation script)")
            self.alsa_plugin_status.setStyleSheet("color: #f44336; font-size: 11px;")

    def _fix_pipewire_permissions(self):
        """Fix PipeWire @clock override."""
        override_dir = Path.home() / ".config/systemd/user/pipewire.service.d"
        override_file = override_dir / "override.conf"
        
        override_dir.mkdir(parents=True, exist_ok=True)
        override_file.write_text("""[Service]
SystemCallFilter=@clock
""")
        
        self.pw_override_status.setText("✓ Configured - restart PipeWire to apply")
        self.pw_override_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        
        QMessageBox.information(
            self, "PipeWire Configuration Updated",
            "The @clock override has been added.\n\n"
            "Run the following to apply:\n"
            "  systemctl --user restart pipewire wireplumber\n\n"
            "Or reboot your system."
        )

    def _test_alsa_device(self):
        """Test inferno ALSA device."""
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
                msg = "Inferno ALSA device found:\n\n" + "\n".join(f"  {l.strip()}" for l in lines)
                QMessageBox.information(self, "ALSA Test Result", msg)
            else:
                QMessageBox.warning(
                    self, "ALSA Test Result",
                    "Inferno ALSA device NOT found in 'aplay -L'\n\n"
                    "Possible issues:\n"
                    "1. ALSA plugin not installed\n"
                    "2. ~/.asoundrc not configured correctly\n"
                    "3. PipeWire needs restart"
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to test ALSA: {e}")

    def load_settings(self):
        """Load settings from config files and QSettings."""
        settings = QSettings("InfernoGUI", "control")  # Use same group as control tab
        
        # Load inferno config
        if self.inferno_config.load():
            self.device_name.setText(self.inferno_config.name)
            idx = self.sample_rate.findData(self.inferno_config.sample_rate)
            if idx >= 0:
                self.sample_rate.setCurrentIndex(idx)
            self.tx_channels.setValue(self.inferno_config.tx_channels)
            self.rx_channels.setValue(self.inferno_config.rx_channels)
        
        # Load interface selection
        saved_iface = settings.value("selected_interface", "", type=str)
        # Don't call _refresh_interfaces here - it's already called in _init_ui
        # Just restore the selection if we have a saved interface
        if saved_iface:
            idx = self.iface_combo.findData(saved_iface)
            if idx >= 0:
                self.iface_combo.setCurrentIndex(idx)
        
        # Load PTP version
        ptp_ver = settings.value("ptp_version", "v2", type=str)
        if ptp_ver == 'v1':
            self.ptp_v1_radio.setChecked(True)
        else:
            self.ptp_v2_radio.setChecked(True)
        
        # Load advanced statime settings
        self.ptp_domain.setValue(settings.value("ptp_domain", 0, type=int))
        self.sync_interval.setValue(settings.value("sync_interval", 0, type=int))
        self.announce_interval.setValue(settings.value("announce_interval", 1, type=int))
        self.log_level.setCurrentText(settings.value("log_level", "INFO", type=str))

    def _capture_original_values(self):
        """Capture current values as baseline for dirty tracking."""
        self._original_values = {
            'device_name': self.device_name.text(),
            'sample_rate': self.sample_rate.currentData(),
            'tx_channels': self.tx_channels.value(),
            'rx_channels': self.rx_channels.value(),
            'ptp_domain': self.ptp_domain.value(),
            'sync_interval': self.sync_interval.value(),
            'announce_interval': self.announce_interval.value(),
            'log_level': self.log_level.currentText(),
            'interface': self.iface_combo.currentData(),
            'ptp_version': 'v1' if self.ptp_v1_radio.isChecked() else 'v2',
        }
        self._dirty = False
        self.dirty_changed.emit(False)
    
    def _mark_dirty(self):
        """Mark settings as having unsaved changes."""
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)
            # Visual feedback - add asterisk to save button
            self.save_btn.setText("💾 Save Configuration*")
            self.save_btn.setStyleSheet("""
                QPushButton { background-color: #FF9800; color: white; border: none;
                              padding: 10px 20px; font-size: 13px; font-weight: bold;
                              border-radius: 4px; }
                QPushButton:hover { background-color: #F57C00; }
            """)
    
    def _check_dirty(self) -> bool:
        """Check if current values differ from original."""
        current = {
            'device_name': self.device_name.text(),
            'sample_rate': self.sample_rate.currentData(),
            'tx_channels': self.tx_channels.value(),
            'rx_channels': self.rx_channels.value(),
            'ptp_domain': self.ptp_domain.value(),
            'sync_interval': self.sync_interval.value(),
            'announce_interval': self.announce_interval.value(),
            'log_level': self.log_level.currentText(),
            'interface': self.iface_combo.currentData(),
            'ptp_version': 'v1' if self.ptp_v1_radio.isChecked() else 'v2',
        }
        return current != self._original_values
    
    def _setup_dirty_tracking(self):
        """Connect all input widgets to dirty tracking."""
        widgets = [
            self.device_name,
            self.sample_rate,
            self.tx_channels,
            self.rx_channels,
            self.ptp_domain,
            self.sync_interval,
            self.announce_interval,
            self.log_level,
            self.iface_combo,
            self.ptp_v1_radio,
            self.ptp_v2_radio,
        ]
        for w in widgets:
            if hasattr(w, 'textChanged'):
                w.textChanged.connect(self._mark_dirty)
            elif hasattr(w, 'currentIndexChanged'):
                w.currentIndexChanged.connect(self._mark_dirty)
            elif hasattr(w, 'valueChanged'):
                w.valueChanged.connect(self._mark_dirty)
            elif hasattr(w, 'toggled'):
                w.toggled.connect(self._mark_dirty)
    
    def save_settings(self):
        """Save all settings to config files."""
        settings = QSettings("InfernoGUI", "control")  # Use same group as control tab
        
        # Save inferno config
        self.inferno_config.set('name', self.device_name.text())
        self.inferno_config.set('sample_rate', self.sample_rate.currentData())
        self.inferno_config.set('tx_channels', self.tx_channels.value())
        self.inferno_config.set('rx_channels', self.rx_channels.value())
        self.inferno_config.save()
        
        # Save interface
        iface = self.iface_combo.currentData()
        if iface:
            settings.setValue("selected_interface", iface)
        
        # Save PTP version
        ptp_ver = 'v1' if self.ptp_v1_radio.isChecked() else 'v2'
        settings.setValue("ptp_version", ptp_ver)
        
        # Save advanced settings
        settings.setValue("ptp_domain", self.ptp_domain.value())
        settings.setValue("sync_interval", self.sync_interval.value())
        settings.setValue("announce_interval", self.announce_interval.value())
        settings.setValue("log_level", self.log_level.currentText())
        
        # Update statime configs with advanced settings
        self._update_statime_configs()
        
        # Notify control tab
        if self.control_tab:
            self.control_tab.set_interface(iface)
            self.control_tab.set_ptp_version(ptp_ver)
        
        self.settings_changed.emit()
        
        # Reset dirty state
        self._capture_original_values()
        
        QMessageBox.information(
            self, "Settings Saved",
            "Configuration saved successfully.\n\n"
            "Note: Changes to audio parameters (sample rate, channels) "
            "require restarting any applications using the Inferno device."
        )
    
    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self._dirty or self._check_dirty()
    
    def auto_save_if_dirty(self) -> bool:
        """Save settings if there are unsaved changes. Returns True if saved or no changes."""
        if self.has_unsaved_changes():
            self.save_settings()
            return True
        return True
    
    def _update_statime_configs(self):
        """Update both statime config files with advanced settings."""
        from inferno_gui.core.config import get_default_statime_config, StatimeConfig
        
        for ptp_ver in ['v1', 'v2']:
            config_path = get_default_statime_config(ptp_ver)
            if config_path.exists():
                try:
                    cfg = StatimeConfig(str(config_path))
                    if cfg.load():
                        # Handle both config formats (flat vs [global] section)
                        # Try flat format first (installed format)
                        if cfg.get('domain') is not None:
                            cfg.set('domain', self.ptp_domain.value())
                        else:
                            cfg.set('global.domain', self.ptp_domain.value())
                        
                        if cfg.get('loglevel') is not None:
                            cfg.set('loglevel', self.log_level.currentText().lower())
                        elif cfg.get('global.log_level') is not None:
                            cfg.set('global.log_level', self.log_level.currentText().lower())
                        else:
                            cfg.set('log_level', self.log_level.currentText().lower())
                        
                        # Port settings - use hyphenated names as statime expects
                        cfg.set('port[0].sync-interval', self.sync_interval.value())
                        cfg.set('port[0].announce-interval', self.announce_interval.value())
                        cfg.save()
                except Exception:
                    pass  # Ignore config update errors

    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Reset all settings to default values?\n"
            "This will overwrite ~/.asoundrc and statime configs.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.device_name.setText("Inferno")
            self.sample_rate.setCurrentText("48000 Hz")
            self.tx_channels.setValue(24)
            self.rx_channels.setValue(24)
            self.ptp_domain.setValue(0)
            self.sync_interval.setValue(0)
            self.announce_interval.setValue(1)
            self.log_level.setCurrentText("INFO")
            self.ptp_v2_radio.setChecked(True)
            self.save_settings()

    def set_interface(self, iface: str):
        """Set interface from control tab."""
        idx = self.iface_combo.findData(iface)
        if idx >= 0:
            self.iface_combo.setCurrentIndex(idx)

    def set_ptp_version(self, version: str):
        """Set PTP version from control tab."""
        if version == 'v1':
            self.ptp_v1_radio.setChecked(True)
        else:
            self.ptp_v2_radio.setChecked(True)

    def set_running_state(self, running: bool):
        """Disable/enable settings when inferno is running."""
        # Only update if state actually changes (idempotent)
        current_enabled = self.iface_combo.isEnabled()
        if current_enabled == running:
            return  # Already in correct state
            
        enabled = not running
        self.iface_combo.setEnabled(enabled)
        self.refresh_iface_btn.setEnabled(enabled)
        self.ptp_v1_radio.setEnabled(enabled)
        self.ptp_v2_radio.setEnabled(enabled)
        self.device_name.setEnabled(enabled)
        self.sample_rate.setEnabled(enabled)
        self.tx_channels.setEnabled(enabled)
        self.rx_channels.setEnabled(enabled)
        self.ptp_domain.setEnabled(enabled)
        self.sync_interval.setEnabled(enabled)
        self.announce_interval.setEnabled(enabled)
        self.log_level.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.reset_btn.setEnabled(enabled)
        
        # Visual indication
        if running:
            self.setStyleSheet("""
                QGroupBox { color: #888; }
                QLabel { color: #888; }
            """)
        else:
            self.setStyleSheet("")

    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self._dirty or self._check_dirty()
    
    def auto_save_if_dirty(self) -> bool:
        """Save settings if there are unsaved changes. Returns True if saved or no changes."""
        if self.has_unsaved_changes():
            self.save_settings()
            return True
        return True


# Need QTimer import
from PyQt6.QtCore import QTimer