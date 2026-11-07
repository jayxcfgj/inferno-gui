#!/usr/bin/env python3
"""
Main entry point for Inferno GUI application.
"""

import os
import sys
import signal

def main():
    # Check for root privileges (needed for statime PTP)
    if os.getuid() != 0:
        print(f"{__app_name__} requires root privileges for PTP hardware timestamping.", file=sys.stderr)
        print("Please run: sudo python3 -m inferno_gui", file=sys.stderr)
        sys.exit(1)

    # Set up signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from pathlib import Path

    from inferno_gui.ui.main_window import MainWindow
    from inferno_gui.core.version import __app_name__

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("InfernoGUI")
    app.setOrganizationDomain("inferno-gui.local")

    # Set application icon
    icon_path = Path(__file__).parent / 'assets' / 'icon.png'
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()