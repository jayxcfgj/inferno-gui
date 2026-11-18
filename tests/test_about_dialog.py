# tests/test_about_dialog.py
"""About dialog: SVG header with PNG fallback, three GitHub link buttons
wired to url_utils.open_url_as_user, and a fixed size that fits the
whole button row without clipping.

The header must prefer assets/about_header.svg (rendered by the QtSvg
image-format plugin), fall back to the PNG and finally to a text label.
The link buttons must go through open_url_as_user — the GUI runs as
root, so QDesktopServices would open the browser in root's session.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_about_dialog.py -v
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import pytest
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from inferno_gui.ui.about_dialog import AboutDialog

# PyQt hält keine Referenz auf die QApplication: wird der Python-Wrapper
# garbage-collected, zerstört Qt die App samt aller Widgets. Deshalb die
# Referenz modulglobal halten (Muster tests/test_url_utils.py).
_APP = None


def _get_app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture
def qt_offscreen():
    """QApplication bereitstellen (modulglobal gehalten)."""
    return _get_app()


ASSETS = Path(__file__).resolve().parents[1] / "inferno_gui" / "assets"
SVG_PATH = ASSETS / "about_header.svg"

EXPECTED_LINKS = (
    ("Inferno GitHub", "https://github.com/teodly/inferno"),
    ("Statime GitHub", "https://github.com/teodly/statime"),
    ("Inferno GUI GitHub", "https://github.com/jayxcfgj/inferno-gui"),
)


def _link_buttons(dlg):
    """Alle GitHub-Buttons des Dialogs (schwarzbox, in beliebiger Reihenfolge)."""
    return [b for b in dlg.findChildren(QPushButton) if b.text().endswith("GitHub")]


# ── (a) Header: SVG wird geladen und verwendet ─────────────────────
def test_qt_svg_plugin_loads_header(qt_offscreen):
    """Umgebungs-Wächter: QPixmap rendert das gebündelte SVG (QtSvg-Plugin)."""
    assert SVG_PATH.exists(), f"missing asset: {SVG_PATH}"
    pm = QPixmap(str(SVG_PATH))
    assert not pm.isNull(), "QtSvg plugin not available — svg header renders null"


def test_header_loaded_from_svg(qt_offscreen):
    """Der Header stammt aus der SVG-Datei (nicht aus dem PNG-Fallback)."""
    dlg = AboutDialog()
    assert Path(dlg.header_source) == SVG_PATH, \
        f"header must come from the svg, got {dlg.header_source!r}"
    label = dlg.findChild(QLabel, "aboutHeader")
    assert label is not None, "header image label (objectName 'aboutHeader') missing"
    pm = label.pixmap()
    assert pm is not None and not pm.isNull(), "displayed header pixmap is null"


def test_header_falls_back_to_png_when_svg_fails(qt_offscreen, monkeypatch):
    """Kann das SVG nicht geladen werden, gewinnt das PNG (Fallback-Kette)."""
    from inferno_gui.ui import about_dialog as mod

    real_qpixmap = QPixmap

    def fake_qpixmap(path=None):
        if isinstance(path, str) and path.endswith(".svg"):
            return real_qpixmap()  # simuliert: SVG-Plugin fehlt/Datei defekt
        return real_qpixmap(str(ASSETS / "about_header.png"))

    monkeypatch.setattr(mod, "QPixmap", fake_qpixmap)
    dlg = mod.AboutDialog()
    assert Path(dlg.header_source).name == "about_header.png"
    assert dlg.findChild(QLabel, "aboutHeader") is not None


def test_header_falls_back_to_text_when_no_image_loads(qt_offscreen, monkeypatch):
    """Ohne Bild (auch PNG defekt) zeigt der Dialog den Text-Platzhalter."""
    from inferno_gui.ui import about_dialog as mod

    monkeypatch.setattr(mod, "QPixmap", lambda path=None: QPixmap())
    dlg = mod.AboutDialog()
    assert dlg.header_source is None
    assert dlg.findChild(QLabel, "aboutHeader") is None


# ── (b) Genau drei Link-Buttons mit den erwarteten Labels ─────────
def test_exactly_three_link_buttons(qt_offscreen):
    dlg = AboutDialog()
    buttons = _link_buttons(dlg)
    assert len(buttons) == 3, \
        f"expected 3 GitHub buttons, found: {[b.text() for b in buttons]}"
    assert {b.text() for b in buttons} == {t for t, _ in EXPECTED_LINKS}


# ── (c) Klicks laufen über open_url_as_user mit exakter URL ───────
def test_link_buttons_open_via_url_helper(qt_offscreen, monkeypatch):
    dlg = AboutDialog()
    calls = []
    monkeypatch.setattr(
        "inferno_gui.ui.about_dialog.open_url_as_user", calls.append
    )
    for text, url in EXPECTED_LINKS:
        calls.clear()
        btn = next(b for b in _link_buttons(dlg) if b.text() == text)
        btn.click()
        assert calls == [url], \
            f"{text} must open {url!r} via open_url_as_user, got {calls!r}"


# ── (d) Feste Dialoggröße passt alle Buttons (Geometrie-Sonde) ─────
def test_dialog_fits_all_link_buttons(qt_offscreen):
    """Alle drei Buttons liegen sichtbar + enabled vollständig im Dialog
    (kein Clipping am rechten Rand)."""
    dlg = AboutDialog()
    dlg.show()  # Layout muss aktiv sein, sonst ist die Geometrie ungültig
    _get_app().processEvents()
    assert dlg.width() == 460 and dlg.height() == 520, \
        f"fixed size changed: {dlg.width()}x{dlg.height()}"
    for text, _url in EXPECTED_LINKS:
        btn = next(b for b in _link_buttons(dlg) if b.text() == text)
        assert btn.isEnabled(), f"{text} must be enabled"
        assert btn.isVisibleTo(dlg), f"{text} must be visible"
        assert dlg.rect().contains(btn.geometry()), \
            f"{text} clipped: {btn.geometry()} outside {dlg.rect()}"
