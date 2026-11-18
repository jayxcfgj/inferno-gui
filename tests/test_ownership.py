"""Files written by the sudo-launched GUI must end up owned by the
invoking user: root-owned ~/.asoundrc, statime TOMLs and QSettings files
could no longer be edited by a later normal (non-sudo) run.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ownership.py -q
"""
import os
import pwd
import re
import sys
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QMessageBox

from inferno_gui.core.app_settings import user_settings
from inferno_gui.core.config import InfernoConfig, StatimeConfig

# Hold a module-level reference: a temporary QApplication() expression is
# garbage-collected immediately, which aborts later widget construction.
_app = QApplication.instance() or QApplication(sys.argv)

INSTALLER = Path(__file__).resolve().parent.parent / "install_inferno.sh"


def _me() -> pwd.struct_passwd:
    """The account the tests run as; SUDO_USER lookups resolve to it."""
    return pwd.getpwuid(os.getuid())


def _root_owned_files(*paths):
    """Context manager: the listed files report root:root ownership.

    Real stat data is kept for every path (os.path.exists keeps
    working); only the uid/gid of the listed files are zeroed, pretending
    root wrote them.
    """
    real_stat = os.stat
    listed = {os.fspath(p) for p in paths}

    def fake_stat(path, *args, **kwargs):
        st = real_stat(os.fspath(path), *args, **kwargs)
        if os.fspath(path) not in listed:
            return st
        return os.stat_result(
            (st.st_mode, st.st_ino, st.st_dev, st.st_nlink, 0, 0,
             st.st_size, st.st_atime, st.st_mtime, st.st_ctime)
        )

    return mock.patch("os.stat", side_effect=fake_stat)


def _fake_interfaces(monkeypatch, ifaces, ips=None):
    """Force the detected interface list and IPs (pattern from
    tests/test_interface_persistence.py)."""
    import inferno_gui.core.config as config
    import inferno_gui.ui.settings_tab as settings_tab
    ips = ips or {}
    monkeypatch.setattr(config, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(config, "get_interface_ip", lambda iface: ips.get(iface))
    monkeypatch.setattr(settings_tab, "get_available_interfaces", lambda: list(ifaces))
    monkeypatch.setattr(settings_tab, "get_interface_ip", lambda iface: ips.get(iface))


def _fake_home(monkeypatch, tmp_path):
    """Redirect both get_actual_user_home references to a fresh fake home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import inferno_gui.core.app_settings as app_settings
    import inferno_gui.core.config as config
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(config, "get_actual_user_home", lambda: fake_home)
    return fake_home


def _installer_content() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def _installer_section(start_marker: str) -> str:
    """Body of one top-level bash function.

    Unlike tests/test_installer_pipewire.py's _section (which cuts at the
    first column-0 '}'), this variant stops at the next top-level
    function definition: step_configure_alsa's .asoundrc heredoc already
    contains a column-0 '}'.
    """
    after = _installer_content().split(start_marker, 1)[1]
    m = re.search(r"\n[a-zA-Z_][a-zA-Z0-9_]*\(\) \{", after)
    return after[: m.start()] if m else after


# ---------------------------------------------------------------------------
# chown_to_invoking_user / config save() wiring
# ---------------------------------------------------------------------------


def test_chown_called_for_saved_configs(monkeypatch, tmp_path):
    """(a) InfernoConfig.save() and StatimeConfig.save() hand their written
    files to the invoking user resolved from SUDO_USER via pwd."""
    from inferno_gui.core import ownership

    monkeypatch.setenv("SUDO_USER", _me().pw_name)

    inferno = InfernoConfig(config_path=tmp_path / ".asoundrc")
    statime = StatimeConfig(str(tmp_path / "inferno-ptpv2.toml"))
    statime.set("global.domain", 0)

    with mock.patch("os.getuid", return_value=0), \
         mock.patch("os.chown") as chown, \
         _root_owned_files(tmp_path / ".asoundrc", tmp_path / "inferno-ptpv2.toml"):
        inferno.save()
        statime.save()

    assert chown.call_count == 2, chown.call_args_list
    chowned = {call.args[0] for call in chown.call_args_list}
    assert chowned == {
        str(tmp_path / ".asoundrc"),
        str(tmp_path / "inferno-ptpv2.toml"),
    }
    for call in chown.call_args_list:
        assert call.args[1:] == (_me().pw_uid, _me().pw_gid)


def test_noop_when_not_root(monkeypatch, tmp_path):
    """(b) Not running as root: saves happen normally, no chown is attempted."""
    monkeypatch.setenv("SUDO_USER", _me().pw_name)

    inferno = InfernoConfig(config_path=tmp_path / ".asoundrc")
    statime = StatimeConfig(str(tmp_path / "inferno-ptpv2.toml"))

    with mock.patch("os.getuid", return_value=1000), \
         mock.patch("os.chown") as chown, \
         _root_owned_files(tmp_path / ".asoundrc", tmp_path / "inferno-ptpv2.toml"):
        inferno.save()
        statime.save()

    chown.assert_not_called()
    assert (tmp_path / ".asoundrc").exists()
    assert (tmp_path / "inferno-ptpv2.toml").exists()


def test_noop_when_already_owned(monkeypatch, tmp_path):
    """A file that already belongs to the invoking user is left alone."""
    from inferno_gui.core import ownership

    monkeypatch.setenv("SUDO_USER", _me().pw_name)
    target = tmp_path / ".asoundrc"
    target.write_text("pcm.inferno {}\n")

    with mock.patch("os.getuid", return_value=0), mock.patch("os.chown") as chown:
        # No _root_owned_files(): the file really belongs to _me().
        ownership.chown_to_invoking_user(target)

    chown.assert_not_called()


def test_chown_errors_are_logged_and_ignored(monkeypatch, tmp_path):
    """chown failures never propagate (a save must not break)."""
    from inferno_gui.core import ownership

    monkeypatch.setenv("SUDO_USER", _me().pw_name)
    target = tmp_path / ".asoundrc"
    target.write_text("pcm.inferno {}\n")

    with mock.patch("os.getuid", return_value=0), \
         _root_owned_files(target), \
         mock.patch("os.chown", side_effect=OSError("operation not permitted")):
        ownership.chown_to_invoking_user(target)  # must not raise


def test_fallback_to_home_owner_when_no_sudo_user(monkeypatch, tmp_path):
    """Without SUDO_USER the owner of get_actual_user_home() is the target."""
    from inferno_gui.core import ownership

    monkeypatch.delenv("SUDO_USER", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(ownership, "get_actual_user_home", lambda: home)

    target = tmp_path / ".asoundrc"
    target.write_text("pcm.inferno {}\n")

    with mock.patch("os.getuid", return_value=0), \
         mock.patch("os.chown") as chown, \
         _root_owned_files(target):
        ownership.chown_to_invoking_user(target)

    assert chown.call_count == 1
    assert chown.call_args.args == (str(target), _me().pw_uid, _me().pw_gid)


# ---------------------------------------------------------------------------
# chown_qsettings / QSettings write wiring
# ---------------------------------------------------------------------------


def test_chown_qsettings_after_save(monkeypatch):
    """(c) chown_qsettings() flushes and hands the settings file over."""
    from inferno_gui.core import ownership

    monkeypatch.setenv("SUDO_USER", _me().pw_name)

    settings = user_settings("control")
    settings.setValue("selected_interface", "eth0")

    with mock.patch("os.getuid", return_value=0), \
         mock.patch("os.chown") as chown, \
         _root_owned_files(settings.fileName()):
        ownership.chown_qsettings(settings)

    assert chown.call_count == 1
    assert chown.call_args.args == (
        str(settings.fileName()), _me().pw_uid, _me().pw_gid)


def test_settings_tab_save_chowns_qsettings_file(monkeypatch, tmp_path):
    """SettingsTab.save_settings() hands the QSettings file and .asoundrc
    back to the invoking user."""
    fake_home = _fake_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SUDO_USER", _me().pw_name)
    _fake_interfaces(monkeypatch, ["eth0"])
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
    )

    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    conf = user_settings("control")

    with mock.patch("os.getuid", return_value=0), \
         mock.patch("os.chown") as chown, \
         _root_owned_files(conf.fileName(), fake_home / ".asoundrc"):
        st.save_settings()

    chowned = {call.args[0] for call in chown.call_args_list}
    assert chowned == {str(conf.fileName()), str(fake_home / ".asoundrc")}
    for call in chown.call_args_list:
        assert call.args[1:] == (_me().pw_uid, _me().pw_gid)


def test_main_window_state_save_chowns_qsettings_file(monkeypatch, tmp_path):
    """MainWindow._save_window_state() hands the window-state file over."""
    fake_home = _fake_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SUDO_USER", _me().pw_name)
    _fake_interfaces(monkeypatch, ["eth0"])

    from inferno_gui.ui.main_window import MainWindow
    mw = MainWindow()
    conf = user_settings("window")

    with mock.patch("os.getuid", return_value=0), \
         mock.patch("os.chown") as chown, \
         _root_owned_files(conf.fileName()):
        mw._save_window_state()

    assert chown.call_count == 1, chown.call_args_list
    assert chown.call_args.args[0] == str(conf.fileName())
    mw.hide()


# ---------------------------------------------------------------------------
# installer: hand $WORK_DIR and $ASOUNDRC back to the invoking user
# ---------------------------------------------------------------------------


def test_installer_chowns_workdir():
    """(d) Structural: the installer chowns $WORK_DIR (recursively) after
    the statime/inferno build steps and $ASOUNDRC + $WORK_DIR after the
    .asoundrc step; the GUI install step keeps its own chown."""
    workdir_chown = 'chown -R "$SUDO_USER_VAL:$SUDO_USER_VAL" "$WORK_DIR"'
    asoundrc_chown = 'chown "$SUDO_USER_VAL:$SUDO_USER_VAL" "$ASOUNDRC"'

    for marker in ("step_build_statime_inferno() {", "step_build_inferno_plugin() {"):
        body = _installer_section(marker)
        assert workdir_chown in body, marker
        assert '[ "$TEST_MODE" = false ]' in body, marker
        assert '[ -n "$SUDO_USER_VAL" ]' in body, marker
        assert '[ "$SUDO_USER_VAL" != "root" ]' in body, marker
        assert '2>/dev/null || true' in body, marker

    alsa = _installer_section("step_configure_alsa() {")
    assert asoundrc_chown in alsa
    assert workdir_chown in alsa
    assert '[ "$TEST_MODE" = false ]' in alsa
    assert '[ -n "$SUDO_USER_VAL" ]' in alsa
    assert '[ "$SUDO_USER_VAL" != "root" ]' in alsa
    assert '2>/dev/null || true' in alsa

    gui = _installer_section("step_optional_gui() {")
    assert 'chown -R "$SUDO_USER_VAL:$SUDO_USER_VAL" "$gui_dest"' in gui
