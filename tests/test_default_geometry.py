# tests/test_default_geometry.py
"""Default window height: the taller tab page fits without a scroll bar
and without a large empty band under the content.

The old flat 750px default left dead space at the bottom; the default
now derives from the tab pages (the Settings scroll content height +
tab bar + menu bar) and stays within the 740px budget.  The window
remains freely resizable — no maximum size is imposed.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_default_geometry.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QScrollArea

# PyQt holds no reference to the QApplication: if the Python wrapper is
# garbage-collected, Qt destroys the app with all widgets ("wrapped
# C/C++ object ... has been deleted").  Hold it module-global
# (pattern tests/test_sync_icons.py).
_APP = None


def _get_app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _fake_home(monkeypatch, tmp_path):
    """Fresh settings home (no saved window.conf) + hermetic pw read.

    Redirects get_actual_user_home in app_settings (the scope MainWindow
    saves/restores window state through) and config; read_pipewire_latency
    is patched so showing the Settings tab never shells out (pattern
    tests/test_settings_latency.py::user_home)."""
    import inferno_gui.core.app_settings as app_settings
    import inferno_gui.core.config as config
    import inferno_gui.ui.settings_tab as settings_tab_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(config, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(settings_tab_mod, "read_pipewire_latency", lambda: None)
    return fake_home


def test_default_height_fits_settings_without_scrollbar(monkeypatch, tmp_path):
    app = _get_app()
    _fake_home(monkeypatch, tmp_path)
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    app.processEvents()

    # (a) The default height sits within the 740px budget (the old flat
    # default was 750 with a band of empty space under the content).
    assert mw.height() <= 740, \
        f"default height {mw.height()}px exceeds the 740px budget"

    # (b) ... and it still shows the Settings tab fully: after
    # switching tabs (showEvent refresh included) no vertical scrollbar
    # may appear — the page must fit, not scroll.
    mw.show()
    app.processEvents()
    mw.tabs.setCurrentWidget(mw.settings_tab)
    app.processEvents()

    scroll = mw.settings_tab.findChild(QScrollArea)
    assert scroll is not None, "settings page lost its fallback scroll area"
    assert scroll.verticalScrollBar().maximum() == 0, (
        f"settings page scrolls at the default height: viewport "
        f"{scroll.viewport().height()}px vs content "
        f"{scroll.widget().sizeHint().height()}px")
    # Width clamp keeps the page wide enough: no horizontal scrollbar.
    assert scroll.horizontalScrollBar().maximum() == 0, \
        "horizontal scrollbar appeared at the default width"

    # (c) No wasted band: the viewport exceeds the content's need by
    # only a few px of frame/slack margin, not by a large empty area.
    slack = scroll.viewport().height() - scroll.widget().sizeHint().height()
    assert 0 <= slack <= 12, \
        f"{slack}px of empty space under the settings content"

    # (d) The window stays freely resizable: no maximum size imposed.
    # 16777215 is Qt's QWIDGETSIZE_MAX — the "unset" value.
    assert mw.maximumHeight() == 16777215, \
        "a maximum height was imposed on the window"
    assert mw.maximumWidth() == 16777215, \
        "a maximum width was imposed on the window"

    mw.hide()
    mw.deleteLater()
