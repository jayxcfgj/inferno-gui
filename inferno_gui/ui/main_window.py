"""Main Window for Inferno GUI."""

import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QPushButton, QSystemTrayIcon, QMenu,
    QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import QIcon, QAction, QPixmap, QFont

from inferno_gui.core.version import (
    __version__,
    __app_name__,
    __description__,
    __license__,
    __author__,
)
from inferno_gui.ui.control_tab import ControlTab
from inferno_gui.ui.settings_tab import SettingsTab
from inferno_gui.ui.about_dialog import AboutDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setGeometry(200, 200, 1000, 750)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        
        # State
        self._inferno_running = False
        
        # Setup UI
        self._setup_tabs()
        self._setup_tray()
        self._setup_menu_bar()
        self._load_window_state()
        
        # Connect signals
        self._connect_signals()
        
        # Status update timer
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_window_title)
        self._status_timer.start(2000)

    def _setup_tabs(self):
        """Setup main tab widget."""
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # Create tabs
        self.control_tab = ControlTab()
        self.settings_tab = SettingsTab(control_tab=self.control_tab)
        
        # Link tabs
        self.control_tab.settings_tab = self.settings_tab
        
        self.tabs.addTab(self.control_tab, "🎛  Control")
        self.tabs.addTab(self.settings_tab, "⚙  Settings")

        # About button in tab bar corner
        about_btn = QPushButton("ℹ")
        about_btn.setFixedSize(28, 28)
        about_btn.setToolTip(f"About {__app_name__}")
        about_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #ccc;
                border: none; font-size: 14px; border-radius: 14px;
            }
            QPushButton:hover { background-color: #3d3d3d; color: #fff; }
        """)
        about_btn.clicked.connect(self._show_about)
        self.tabs.setCornerWidget(about_btn, Qt.Corner.TopRightCorner)

    def _setup_tray(self):
        """Setup system tray icon."""
        self.tray_icon = QSystemTrayIcon(self)
        
        # Try to load icon
        icon_path = Path(__file__).parent.parent / 'assets' / 'icon.png'
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))
        else:
            # Create a simple colored icon
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            from PyQt6.QtGui import QPainter, QBrush, QColor
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(QColor("#4CAF50")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(4, 4, 24, 24)
            painter.end()
            self.tray_icon.setIcon(QIcon(pixmap))
        
        self.tray_icon.setToolTip(f"{__app_name__} - Dante/AES67 Virtual Soundcard")
        
        # Tray menu
        tray_menu = QMenu()
        
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        # Quick start/stop from tray
        self.tray_start_action = QAction("▶ Start PTP", self)
        self.tray_start_action.triggered.connect(self.control_tab.start_ptp)
        tray_menu.addAction(self.tray_start_action)
        
        self.tray_stop_action = QAction("■ Stop PTP", self)
        self.tray_stop_action.triggered.connect(self.control_tab.stop_ptp)
        self.tray_stop_action.setEnabled(False)
        tray_menu.addAction(self.tray_stop_action)
        
        tray_menu.addSeparator()
        
        netaudio_action = QAction("🌐 Open NetAudio Web UI", self)
        netaudio_action.triggered.connect(self.control_tab._open_netaudio)
        tray_menu.addAction(netaudio_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _setup_menu_bar(self):
        """Setup menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        save_action = QAction("Save Settings", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.settings_tab.save_settings)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        toggle_tray_action = QAction("Show Tray Icon", self)
        toggle_tray_action.setCheckable(True)
        toggle_tray_action.setChecked(True)
        toggle_tray_action.toggled.connect(self.tray_icon.setVisible)
        view_menu.addAction(toggle_tray_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction(f"About {__app_name__}", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
        inferno_github = QAction("Inferno GitHub", self)
        inferno_github.triggered.connect(lambda: self._open_url("https://github.com/teodly/inferno"))
        help_menu.addAction(inferno_github)
        
        statime_github = QAction("Statime GitHub", self)
        statime_github.triggered.connect(lambda: self._open_url("https://github.com/teodly/statime"))
        help_menu.addAction(statime_github)

    def _connect_signals(self):
        """Connect signals between tabs."""
        # Control tab signals
        self.control_tab.ptp_started.connect(self._on_ptp_started)
        self.control_tab.ptp_stopped.connect(self._on_ptp_stopped)
        self.control_tab.inferno_started.connect(self._on_inferno_started)
        self.control_tab.inferno_stopped.connect(self._on_inferno_stopped)
        
        # Settings tab signals
        self.settings_tab.interface_changed.connect(self.control_tab.set_interface)
        self.settings_tab.ptp_version_changed.connect(self.control_tab.set_ptp_version)
        self.settings_tab.settings_changed.connect(self._on_settings_changed)

    def _on_ptp_started(self):
        """Handle PTP started."""
        self._inferno_running = True
        self._update_tray_actions()
        self.settings_tab.set_running_state(True)

    def _on_ptp_stopped(self):
        """Handle PTP stopped."""
        self._inferno_running = False
        self._update_tray_actions()
        self.settings_tab.set_running_state(False)

    def _on_inferno_started(self):
        """Handle Inferno started."""
        pass  # Inferno is auto-started by PipeWire

    def _on_inferno_stopped(self):
        """Handle Inferno stopped."""
        pass

    def _on_settings_changed(self):
        """Handle settings changed."""
        # Update control tab if needed
        pass

    def _update_tray_actions(self):
        """Update tray menu actions based on state."""
        self.tray_start_action.setEnabled(not self._inferno_running)
        self.tray_stop_action.setEnabled(self._inferno_running)
        
        if self._inferno_running:
            self.tray_icon.setToolTip(f"{__app_name__} - PTP Running")
        else:
            self.tray_icon.setToolTip(f"{__app_name__} - Stopped")

    def _update_window_title(self):
        """Update window title with status."""
        if self._inferno_running:
            ptp_status = self.control_tab.get_ptp_status()
            state = ptp_status.get('state', 'RUNNING')
            offset = ptp_status.get('offset')
            if offset is not None:
                self.setWindowTitle(f"{__app_name__} v{__version__} - PTP: {state} ({offset}ns)")
            else:
                self.setWindowTitle(f"{__app_name__} v{__version__} - PTP: {state}")
        else:
            self.setWindowTitle(f"{__app_name__} v{__version__}")

    def _tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _show_window(self):
        """Show and raise the main window."""
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_about(self):
        """Show about dialog."""
        AboutDialog(self).exec()

    def _open_url(self, url: str):
        """Open URL in default browser."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _load_window_state(self):
        """Load window geometry and state."""
        settings = QSettings("InfernoGUI", "window")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = settings.value("windowState")
        if state:
            self.restoreState(state)

    def _save_window_state(self):
        """Save window geometry and state."""
        settings = QSettings("InfernoGUI", "window")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

    def closeEvent(self, event):
        """Handle close event - minimize to tray instead of quitting."""
        if self.tray_icon.isVisible():
            QMessageBox.information(
                self, __app_name__,
                f"{__app_name__} will continue running in the system tray.\n"
                "Use the tray icon to show the window or quit the application.",
                QMessageBox.StandardButton.Ok
            )
            self.hide()
            event.ignore()
        else:
            self._save_window_state()
            self.tray_icon.hide()
            event.accept()

    def showEvent(self, event):
        """Handle show event."""
        super().showEvent(event)
        # Refresh interfaces when window shown
        self.control_tab._refresh_interfaces()
        self.settings_tab._refresh_interfaces()