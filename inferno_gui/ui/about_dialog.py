"""About dialog for Inferno GUI."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap, QDesktopServices
from PyQt6.QtCore import QUrl
from pathlib import Path

from inferno_gui.core.version import (
    __version__,
    __app_name__,
    __description__,
    __license__,
    __author__,
    __inferno_author__,
)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'About {__app_name__}')
        self.setFixedSize(460, 520)
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QPushButton {
                background-color: #3d3d3d; color: #e0e0e0;
                border: 1px solid #555; padding: 6px 16px;
                border-radius: 4px; font-size: 12px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        # Hero image / logo area
        img_path = str(Path(__file__).parent.parent / 'assets' / 'about_header.png')
        pixmap = QPixmap(img_path)
        if not pixmap.isNull():
            img = QLabel()
            img.setPixmap(pixmap.scaled(
                400, 160, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(img)
        else:
            # Placeholder text if no image
            title = QLabel(__app_name__)
            title.setFont(QFont('', 18, QFont.Weight.Bold))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

        # App name and version
        app_title = QLabel(__app_name__)
        app_title.setFont(QFont('', 16, QFont.Weight.Bold))
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(app_title)

        ver = QLabel(f'v{__version__}')
        ver.setFont(QFont('', 11))
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet('color: #888;')
        layout.addWidget(ver)

        layout.addSpacing(8)

        # Description
        desc = QLabel(__description__)
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        layout.addSpacing(10)

        # Authors
        inferno_label = QLabel(f'Inferno/statime by {__inferno_author__}')
        inferno_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inferno_label.setStyleSheet('color: #aaa; font-size: 11px;')
        layout.addWidget(inferno_label)

        gui_label = QLabel(f'GUI by {__author__}')
        gui_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gui_label.setStyleSheet('color: #aaa; font-size: 11px;')
        layout.addWidget(gui_label)

        layout.addSpacing(6)

        # License
        lic = QLabel(f'{__license__} License')
        lic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lic.setStyleSheet('color: #666; font-size: 10px;')
        layout.addWidget(lic)

        layout.addSpacing(10)

        # Links
        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        inferno_link = QPushButton('Inferno GitHub')
        inferno_link.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://github.com/teodly/inferno')
        ))
        links_layout.addWidget(inferno_link)
        
        statime_link = QPushButton('Statime GitHub')
        statime_link.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://github.com/teodly/statime')
        ))
        links_layout.addWidget(statime_link)
        
        layout.addLayout(links_layout)

        layout.addSpacing(10)

        # OK button
        btn = QPushButton('OK')
        btn.setFixedWidth(80)
        btn.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)