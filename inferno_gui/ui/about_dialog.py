"""About dialog for Inferno GUI."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from pathlib import Path

from inferno_gui.core.version import (
    __version__,
    __app_name__,
    __description__,
    __license__,
    __author__,
    __inferno_author__,
)
from inferno_gui.ui.url_utils import open_url_as_user

# Label → repo URL for the link buttons.  They open via
# open_url_as_user (the GUI runs as root; QDesktopServices would
# launch the browser in root's session, where nothing opens).
_GITHUB_LINKS = (
    ('Inferno GitHub', 'https://github.com/teodly/inferno'),
    ('Statime GitHub', 'https://github.com/teodly/statime'),
    ('Inferno GUI GitHub', 'https://github.com/jayxcfgj/inferno-gui'),
)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Path of the header image that actually loaded (svg preferred,
        # png fallback, None = text placeholder).  Set by _load_header_pixmap.
        self.header_source = None
        self.setWindowTitle(f'About {__app_name__}')
        # 460 wide fits the three GitHub buttons on one row
        # (row size hint ≈ 395 px, centered, right edge ≈ 428 px).
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

    def _load_header_pixmap(self):
        """Load the header image: SVG first, then PNG, else None.

        QPixmap renders SVGs through the QtSvg image-format plugin, so
        one loader covers both files; the PNG stays as a fallback for
        systems without that plugin.
        """
        assets = Path(__file__).parent.parent / 'assets'
        for name in ('about_header.svg', 'about_header.png'):
            pixmap = QPixmap(str(assets / name))
            if not pixmap.isNull():
                self.header_source = assets / name
                return pixmap
        return None

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        # Hero image / logo area (SVG via QtSvg, PNG fallback, text last)
        pixmap = self._load_header_pixmap()
        if pixmap is not None:
            img = QLabel()
            img.setObjectName('aboutHeader')
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

        # Links — open on the invoking user's desktop, not in root's session
        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for label, url in _GITHUB_LINKS:
            link = QPushButton(label)
            link.clicked.connect(
                lambda _checked=False, u=url: open_url_as_user(u)
            )
            links_layout.addWidget(link)

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