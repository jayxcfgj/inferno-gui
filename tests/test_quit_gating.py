# tests/test_quit_gating.py
"""Quit is offered only while PTP is stopped (close dialog + tray menu).

(a) close-event dialog: three buttons — Minimize to Tray (the default,
    unchanged behavior), Cancel, and Quit now; Quit is DISABLED with an
    explanatory tooltip while PTP runs and ENABLED when stopped.
(b) tray Quit action: same gate, and the enabled state follows the live
    ptp_started/ptp_stopped signals (the same path that drives the
    running-state lock and the tray start/stop actions).
(c) clicking an ENABLED Quit actually exits the app: event accepted,
    window closed, tray hidden, QApplication quit requested; the
    default Minimize path and Cancel stay untouched.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_quit_gating.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QMessageBox

# Exact gating tooltip (spec wording): quitting mid-run would drop all
# active audio, so Quit explains why it is locked.
QUIT_RUNNING_TOOLTIP = (
    "Stop PTP first — quitting while inferno is running would drop all "
    "active audio."
)

# PyQt holds no reference to the QApplication: module-global, like
# tests/test_sync_icons.py.
_APP = None


def _get_app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _fake_home(monkeypatch, tmp_path):
    """Fresh settings home (window.conf must not exist) + hermetic pw read
    (pattern tests/test_default_geometry.py)."""
    import inferno_gui.core.app_settings as app_settings
    import inferno_gui.core.config as config
    import inferno_gui.ui.settings_tab as settings_tab_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(config, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(settings_tab_mod, "read_pipewire_latency", lambda: None)
    return fake_home


def test_close_dialog_three_buttons_quit_gated(monkeypatch, tmp_path):
    """(i) The close dialog offers three buttons; the Quit button is
    disabled (exact tooltip) while PTP runs, enabled when stopped; the
    default action stays Minimize to Tray."""
    app = _get_app()
    _fake_home(monkeypatch, tmp_path)
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    app.processEvents()

    # Stopped: three buttons, Quit enabled, no gating tooltip.
    mw._inferno_running = False
    box, buttons = mw._build_close_dialog()
    assert {b.text() for b in box.buttons()} == \
        {"Minimize to Tray", "Cancel", "Quit now"}, \
        [b.text() for b in box.buttons()]
    assert buttons["quit"].isEnabled() is True
    assert buttons["quit"].toolTip() == ""
    # The default action is unchanged: Enter minimizes to the tray.
    assert box.defaultButton() is buttons["minimize"]

    # Running: same three buttons, Quit disabled with the exact tooltip.
    mw._inferno_running = True
    box2, buttons2 = mw._build_close_dialog()
    assert {b.text() for b in box2.buttons()} == \
        {"Minimize to Tray", "Cancel", "Quit now"}
    assert buttons2["quit"].isEnabled() is False, \
        "Quit must be disabled while PTP runs"
    assert buttons2["quit"].toolTip() == QUIT_RUNNING_TOOLTIP, \
        buttons2["quit"].toolTip()
    assert box2.defaultButton() is buttons2["minimize"]

    mw.hide()
    mw.deleteLater()


def test_tray_quit_action_follows_ptp_state(monkeypatch, tmp_path):
    """(ii) The tray Quit action starts enabled, disables while PTP runs
    (same tooltip), and re-enables when PTP stops — driven by the real
    ptp_started/ptp_stopped signal path."""
    app = _get_app()
    _fake_home(monkeypatch, tmp_path)
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    app.processEvents()

    # Stopped at startup: Quit is offered, no gating tooltip (QAction
    # echoes the label when no tooltip is set — that is the desired
    # look for an enabled Quit).
    assert mw.tray_quit_action.isEnabled() is True
    assert mw.tray_quit_action.toolTip() != QUIT_RUNNING_TOOLTIP

    # PTP starts (the same signal that locks the settings tab):
    mw.control_tab.ptp_started.emit()
    app.processEvents()
    assert mw.tray_quit_action.isEnabled() is False, \
        "tray Quit must disable while PTP runs"
    assert mw.tray_quit_action.toolTip() == QUIT_RUNNING_TOOLTIP

    # PTP stops: Quit comes back.
    mw.control_tab.ptp_stopped.emit()
    app.processEvents()
    assert mw.tray_quit_action.isEnabled() is True
    assert mw.tray_quit_action.toolTip() != QUIT_RUNNING_TOOLTIP

    mw.hide()
    mw.deleteLater()


def _patch_close_dialog(monkeypatch, answer):
    """Make QMessageBox.exec return immediately and clickedButton()
    report `answer(box)` — offscreen tests cannot click a modal dialog.

    Returns the list of Quit buttons that were offered per exec call."""
    offered = []

    def fake_exec(self):
        offered.append(self)
        return 0

    def fake_clicked(self):
        return answer(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)
    return offered


def _find_button(box, text):
    for b in box.buttons():
        if b.text() == text:
            return b
    return None


def test_enabled_quit_closes_app(monkeypatch, tmp_path):
    """(iii) Clicking an ENABLED Quit fully exits: event accepted, the
    window closes, the tray hides, and the QApplication quit path runs."""
    app = _get_app()
    _fake_home(monkeypatch, tmp_path)
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    app.processEvents()
    mw.show()
    app.processEvents()
    assert mw.tray_icon.isVisible(), \
        "precondition: close must go through the dialog path"
    assert mw._inferno_running is False, \
        "precondition: PTP stopped, so Quit is offered enabled"

    quit_calls = []
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))
    _patch_close_dialog(monkeypatch, lambda box: _find_button(box, "Quit now"))

    assert mw.close() is True, "Quit must accept the close event"
    assert not mw.isVisible(), "the window must close"
    assert mw.tray_icon.isVisible() is False, "the tray icon must hide"
    assert quit_calls == [True], "the QApplication quit path must run"


def test_minimize_stays_the_default_action(monkeypatch, tmp_path):
    """Regression: the pre-existing behavior — dialog answered with the
    default/Minimize action hides the window to the tray instead of
    quitting — is unchanged by the Quit gating."""
    app = _get_app()
    _fake_home(monkeypatch, tmp_path)
    from inferno_gui.ui.main_window import MainWindow

    mw = MainWindow()
    app.processEvents()
    mw.show()
    app.processEvents()

    quit_calls = []
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))

    # (a) Default action (Minimize to Tray pressed): hide + ignore.
    _patch_close_dialog(
        monkeypatch, lambda box: _find_button(box, "Minimize to Tray"))
    assert mw.close() is False, "Minimize must ignore the close event"
    assert mw.isHidden() is True, "the window must hide to the tray"
    assert quit_calls == [], "Minimize must not quit the app"

    # (b) Cancel: keep the window open, ignore the close event.
    mw.show()
    app.processEvents()
    _patch_close_dialog(monkeypatch, lambda box: _find_button(box, "Cancel"))
    assert mw.close() is False, "Cancel must ignore the close event"
    assert mw.isVisible() is True, "Cancel must keep the window visible"
    assert quit_calls == [], "Cancel must not quit the app"

    mw.hide()
    mw.deleteLater()
