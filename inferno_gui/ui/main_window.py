"""Main Window for Inferno GUI."""

import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QPushButton, QSystemTrayIcon, QMenu,
    QMessageBox, QApplication, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction, QPixmap, QFont

from inferno_gui.core.version import (
    __version__,
    __app_name__,
    __description__,
    __license__,
    __author__,
)
from inferno_gui.core.app_settings import user_settings
from inferno_gui.core.ownership import chown_qsettings
from inferno_gui.core.sync_state import display_state, tray_state
from inferno_gui.ui.control_tab import ControlTab
from inferno_gui.ui.settings_tab import SettingsTab
from inferno_gui.ui.about_dialog import AboutDialog
from inferno_gui.ui.url_utils import open_url_as_user

# Gating tooltip for every Quit affordance (close dialog + tray menu):
# quitting while inferno runs would drop all active audio, so Quit is
# offered only when PTP is stopped.
_QUIT_RUNNING_TOOLTIP = (
    "Stop PTP first — quitting while inferno is running would drop all "
    "active audio."
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        # Provisional construction size: the height gets sized to the
        # taller tab page once the tabs exist (see the resize after
        # _setup_menu_bar below — the flat 750 left a band of empty
        # space under the shorter Control tab).
        self.setGeometry(200, 200, 1000, 750)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        
        # State
        self._inferno_running = False

        # Sync-Status-Icons: einmalig cachen (schwarz/weiß = nicht sync,
        # gelb = Syncing, grün = Locked); Merker fuer den Zustandswechsel-
        # Swap, Start 'black'.
        self._icon_not_sync = QIcon(
            str(Path(__file__).parent.parent / 'assets' / 'icon.png'))
        self._icon_syncing = QIcon(
            str(Path(__file__).parent.parent / 'assets' / 'icon_syncing.svg'))
        self._icon_locked = QIcon(
            str(Path(__file__).parent.parent / 'assets' / 'icon.svg'))
        self._sync_icons_state = 'black'
        self._sync_icon_for_state = {
            'black': self._icon_not_sync,
            'yellow': self._icon_syncing,
            'green': self._icon_locked,
        }

        # Setup UI
        self._setup_tabs()
        self._setup_tray()
        self._setup_menu_bar()
        # Default height: just tall enough that the taller tab page
        # (Settings) needs no scroll bar and the shorter one (Control)
        # trails into no large empty area; width keeps the 1000 default.
        self.resize(1000, self._default_window_height())
        self._load_window_state()
        self.settings_tab.load_settings()  # Settings beim Start laden

        # Open at the smallest possible width (per spec; height/position stay saved)
        if not self.isMaximized():
            self.resize(self.minimumSizeHint().width(), self.height())
        
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
            self.tray_icon.setIcon(self._icon_not_sync)
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
        
        self.tray_netaudio_action = QAction("🌐 Dante Routing - Open NetAudio Web UI", self)
        self.tray_netaudio_action.triggered.connect(self.control_tab._open_netaudio)
        tray_menu.addAction(self.tray_netaudio_action)
        
        self.tray_qpwgraph_action = QAction("PipeWire Routing - Open qpwgraph", self)
        self.tray_qpwgraph_action.triggered.connect(self.control_tab._open_qpwgraph)
        tray_menu.addAction(self.tray_qpwgraph_action)
        
        self.tray_cable_action = QAction("PipeWire Settings - Open Cable", self)
        self.tray_cable_action.triggered.connect(self.control_tab._open_cable)
        tray_menu.addAction(self.tray_cable_action)
        
        tray_menu.addSeparator()
        
        self.tray_quit_action = QAction("Quit", self)
        self.tray_quit_action.triggered.connect(QApplication.instance().quit)
        # Gated like the close dialog's Quit button: enabled only while
        # PTP is stopped; _update_tray_actions keeps it in sync whenever
        # PTP starts/stops.
        self.tray_quit_action.setEnabled(not self._inferno_running)
        tray_menu.addAction(self.tray_quit_action)
        
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
        inferno_github.triggered.connect(
            lambda: open_url_as_user("https://github.com/teodly/inferno"))
        help_menu.addAction(inferno_github)
        
        statime_github = QAction("Statime GitHub", self)
        statime_github.triggered.connect(
            lambda: open_url_as_user("https://github.com/teodly/statime"))
        help_menu.addAction(statime_github)

    def _connect_signals(self):
        """Connect signals between tabs."""
        # Control tab signals
        self.control_tab.ptp_started.connect(self._on_ptp_started)
        self.control_tab.ptp_stopped.connect(self._on_ptp_stopped)
        self.control_tab.inferno_started.connect(self._on_inferno_started)
        self.control_tab.inferno_stopped.connect(self._on_inferno_stopped)
        self.control_tab.status_changed.connect(self._on_sync_status)
        
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
        # Quit follows the same gate as the close dialog: disabled with
        # an explanatory tooltip while inferno runs (quitting would
        # drop all active audio), enabled when stopped.
        self.tray_quit_action.setEnabled(not self._inferno_running)
        if self._inferno_running:
            self.tray_quit_action.setToolTip(_QUIT_RUNNING_TOOLTIP)
        else:
            self.tray_quit_action.setToolTip("")
        
        if self._inferno_running:
            self.tray_icon.setToolTip(f"{__app_name__} - PTP Running")
        else:
            self.tray_icon.setToolTip(f"{__app_name__} - Stopped")

    def _update_window_title(self):
        """Update window title with status (Display-Label via sync_state)."""
        if self._inferno_running:
            ptp_status = self.control_tab.get_ptp_status()
            state = ptp_status.get('state', 'RUNNING')
            offset = ptp_status.get('offset')
            display = display_state(state, offset)
            if offset is not None:
                self.setWindowTitle(f"{__app_name__} v{__version__} - PTP: {display} ({offset}ns)")
            else:
                self.setWindowTitle(f"{__app_name__} v{__version__} - PTP: {display}")
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

    def _default_window_height(self) -> int:
        """Default window height: the taller tab page plus chrome, no more.

        The height derives from the pages (user report: the flat 750px
        default left a band of empty space under the Control tab, and
        on the Settings tab the content ended well above the window
        bottom).  A page's own sizeHint hides its scroll content — the
        Settings tab sizes its scroll area to a compact default, not
        to the content it must show — so a page with a QScrollArea
        contributes its scroll content's sizeHint instead.  Menu bar,
        tab bar and a few px of slack complete the height; the window
        stays freely resizable (no maximum is imposed anywhere).
        """
        def _page_height(page) -> int:
            height = page.sizeHint().height()
            scroll = page.findChild(QScrollArea)
            if scroll is not None and scroll.widget() is not None:
                height = max(height, scroll.widget().sizeHint().height())
            return height

        needed = max(_page_height(self.control_tab),
                     _page_height(self.settings_tab))
        needed += self.tabs.tabBar().sizeHint().height()
        needed += self.menuBar().sizeHint().height()
        # A few px of slack so rounding/frame margins never grow a
        # scroll bar at the default size.
        return needed + 6

    def _load_window_state(self):
        """Load window geometry and state."""
        settings = user_settings("window")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = settings.value("windowState")
        if state:
            self.restoreState(state)

    def _save_window_state(self):
        """Save window geometry and state."""
        settings = user_settings("window")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        # Running under sudo the settings file would stay root-owned;
        # flush and hand it back to the invoking user.
        chown_qsettings(settings)

    def _build_close_dialog(self):
        """Build the close-event dialog (not exec'd): three buttons with
        the quit one gated by the PTP state.

        Buttons: Minimize to Tray (the DEFAULT, unchanged behavior),
        Cancel, and Quit now — the last offered only while PTP is
        stopped: disabled with a tooltip explaining why when inferno
        runs (quitting would drop all active audio).  Factored out of
        closeEvent so tests can inspect the button states directly.

        Returns (box, buttons) with buttons keyed "minimize" / "cancel"
        / "quit".
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(__app_name__)
        box.setText(
            f"{__app_name__} will continue running in the system tray.\n"
            "Use the tray icon to show the window or quit the application."
        )
        minimize = box.addButton(
            "Minimize to Tray", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole)
        quit_btn = box.addButton(
            "Quit now", QMessageBox.ButtonRole.DestructiveRole)
        # The default action is unchanged: Enter minimizes to the tray.
        box.setDefaultButton(minimize)
        if self._inferno_running:
            quit_btn.setEnabled(False)
            quit_btn.setToolTip(_QUIT_RUNNING_TOOLTIP)
        else:
            quit_btn.setEnabled(True)
            quit_btn.setToolTip("")
        return box, {"minimize": minimize, "cancel": cancel, "quit": quit_btn}

    def closeEvent(self, event):
        """Handle close event - minimize to tray instead of quitting.

        The dialog offers three actions: Minimize to Tray (default, the
        unchanged behavior), Cancel, and Quit now.  Quit is offered only
        while PTP is stopped — disabled with a tooltip otherwise — and
        a quit fully exits the GUI immediately (there is nothing to stop
        first, since it can only be clicked while inferno is not
        running).
        """
        if self.tray_icon.isVisible():
            box, buttons = self._build_close_dialog()
            box.exec()
            clicked = box.clickedButton()
            if clicked is buttons["quit"]:
                if self._inferno_running:
                    # Race guard: PTP started while the dialog was open;
                    # quitting now would drop all active audio, so treat
                    # the click as cancelled.
                    event.ignore()
                    return
                self._save_window_state()
                self.tray_icon.hide()
                event.accept()
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                return
            if clicked is buttons["cancel"]:
                # Dialog dismissed without a choice: keep the window.
                event.ignore()
                return
            # Default action (Minimize pressed or dialog dismissed):
            # hide to the tray, app keeps running.
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

    def _on_sync_status(self, status: dict):
        """Icons (Fenster + Tray) dem Sync-Zustand anpassen (Ampel-Logik
        aus sync_state.tray_state): gruen/gelb/schwarz mit Swap nur bei
        Zustandswechsel."""
        color = tray_state(status.get('ptp_state'), status.get('ptp_offset'))
        if color == self._sync_icons_state:
            return
        self._sync_icons_state = color
        icon = self._sync_icon_for_state[color]
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        self.tray_icon.setIcon(icon)
