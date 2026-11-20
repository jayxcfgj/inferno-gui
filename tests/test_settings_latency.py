"""Settings tab: RX/TX latency edit rows and the two-column layout.

Covers the latency-visualization Task 3 contract:
- defaults 10.0 ms, suffix " ms", 0.1 ms resolution, range 1.0–40.0
- .asoundrc ns ⇄ spinbox ms conversion on load/save, other keys survive
- clamp + warning tooltip + dynamic low-latency warning
- reset restores 10.0 ms; dirty tracking includes the spinboxes
- two-column QGridLayout: channels share rows with latency, Actions and
  Config Files share the right column, content fits 760x560 without the
  fallback scroll area needing to scroll.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings_latency.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QGridLayout, QScrollArea,
)

# Hold a module-level reference: a temporary QApplication() expression is
# garbage-collected immediately, which aborts later widget construction.
_app = QApplication.instance() or QApplication(sys.argv)

# Exact warning wording required by the approved spec (verbatim).
WARNING_TOOLTIP = (
    "Below ~1 ms RX underruns become likely — inferno does not clamp "
    "this value. Dante maximum is 40 ms."
)

HINT_TEXT = "Takes effect after the next PTP start"

ASOUNDRC_FIXTURE = """pcm.inferno {
    type inferno

    NAME "TestCard"
    SAMPLE_RATE "48000"

    TX_CHANNELS 24
    RX_CHANNELS 24

    BIND_IP "192.168.1.10"
    RX_LATENCY_NS 5000000
    TX_LATENCY_NS 8000000
}
"""


def _ensure_app() -> QApplication:
    return _app


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


@pytest.fixture
def user_home(monkeypatch, tmp_path):
    """Redirect both get_actual_user_home references to a fresh fake home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import inferno_gui.core.app_settings as app_settings
    import inferno_gui.core.config as config
    monkeypatch.setattr(app_settings, "get_actual_user_home", lambda: fake_home)
    monkeypatch.setattr(config, "get_actual_user_home", lambda: fake_home)
    settings = app_settings.user_settings("control")
    settings.clear()
    settings.sync()
    return fake_home


@pytest.fixture
def silenced_dialogs(monkeypatch):
    """Make save/reset modal dialogs return immediately (offscreen tests)."""
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def _make_tab(monkeypatch, home, asoundrc=None):
    """Build a SettingsTab against the fake home (optionally seeded)."""
    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "10.0.0.1"})
    if asoundrc is not None:
        (home / ".asoundrc").write_text(asoundrc)
    from inferno_gui.ui.settings_tab import SettingsTab
    st = SettingsTab()
    _ensure_app().processEvents()
    return st


def test_defaults_after_construction(user_home, monkeypatch):
    """(a) Fresh tab without .asoundrc: both spinboxes default to 10.0 ms."""
    st = _make_tab(monkeypatch, user_home)

    assert st.rx_latency.value() == 10.0
    assert st.tx_latency.value() == 10.0
    assert st.rx_latency.suffix() == " ms"
    assert st.rx_latency.decimals() == 1


def test_load_reads_latency_from_asoundrc(user_home, monkeypatch):
    """(b) ns keys in the .asoundrc load as ms spinbox values."""
    st = _make_tab(monkeypatch, user_home, ASOUNDRC_FIXTURE)

    assert st.rx_latency.value() == 5.0
    assert st.tx_latency.value() == 8.0
    # the other keys still load alongside the new ones
    assert st.device_name.text() == "TestCard"
    assert st.tx_channels.value() == 24


def test_save_writes_integer_ns_and_keeps_other_keys(
        user_home, monkeypatch, silenced_dialogs):
    """(c) Saving stores integer ns lines; all other .asoundrc keys survive
    the regeneration."""
    st = _make_tab(monkeypatch, user_home, ASOUNDRC_FIXTURE)
    st.rx_latency.setValue(5.0)
    st.tx_latency.setValue(12.5)

    st.save_settings()

    content = (user_home / ".asoundrc").read_text()
    assert "RX_LATENCY_NS 5000000" in content, content
    assert "TX_LATENCY_NS 12500000" in content, content
    # other keys survive the rewrite (Review Focus 3)
    assert 'NAME "TestCard"' in content
    assert 'SAMPLE_RATE "48000"' in content
    assert "TX_CHANNELS 24" in content
    assert "RX_CHANNELS 24" in content
    assert 'BIND_IP "192.168.1.10"' in content


def test_range_clamps_and_warning_tooltip(user_home, monkeypatch):
    """(d) Out-of-range values clamp to 1.0/40.0 and the static tooltip
    carries the exact warning; the dynamic warning tracks the 1.0 floor."""
    st = _make_tab(monkeypatch, user_home)

    # hidden at the default, before any value change
    assert not st.latency_warning.isVisibleTo(st.latency_warning.parentWidget())

    st.rx_latency.setValue(0.5)
    assert st.rx_latency.value() == 1.0
    st.tx_latency.setValue(45.0)
    assert st.tx_latency.value() == 40.0

    for sb in (st.rx_latency, st.tx_latency):
        assert WARNING_TOOLTIP in sb.toolTip(), sb.toolTip()

    # dynamic warning follows the 1.0 ms floor
    st.rx_latency.setValue(1.0)
    assert st.latency_warning.isVisibleTo(st.latency_warning.parentWidget())
    st.rx_latency.setValue(10.0)
    assert not st.latency_warning.isVisibleTo(st.latency_warning.parentWidget())


def test_reset_restores_10ms(user_home, monkeypatch, silenced_dialogs):
    """(e) Reset to Defaults restores 10.0 ms on both spinboxes."""
    st = _make_tab(monkeypatch, user_home)
    st.rx_latency.setValue(5.0)
    st.tx_latency.setValue(12.5)

    st.reset_to_defaults()

    assert st.rx_latency.value() == 10.0
    assert st.tx_latency.value() == 10.0


def test_dirty_tracking_includes_latency(user_home, monkeypatch, silenced_dialogs):
    """Changing a latency spinbox marks the tab dirty; saving clears it."""
    st = _make_tab(monkeypatch, user_home)
    assert st.has_unsaved_changes() is False

    st.rx_latency.setValue(12.5)
    assert st.has_unsaved_changes() is True

    st.save_settings()
    assert st.has_unsaved_changes() is False


def _cell(grid, widget):
    """(row, column, rowSpan, colSpan) of a widget inside a QGridLayout."""
    return grid.getItemPosition(grid.indexOf(widget))


def test_two_column_grid_structure(user_home, monkeypatch):
    """(f) Channels share grid rows with the latency spinboxes; the groups
    form a two-column grid (left: Network/Audio/Advanced; right: Actions
    above Config Files)."""
    st = _make_tab(monkeypatch, user_home)

    # Audio Parameters is a QGridLayout; latency sits beside the channels.
    audio_group = st.tx_channels.parentWidget()
    audio_grid = audio_group.layout()
    assert isinstance(audio_grid, QGridLayout), \
        f"Audio Parameters must be a QGridLayout, got {audio_grid}"

    tx_ch, tx_lat = _cell(audio_grid, st.tx_channels), _cell(audio_grid, st.tx_latency)
    assert tx_ch[0] == tx_lat[0], "TX latency must share the TX Channels row"
    assert tx_lat[1] > tx_ch[1], "TX latency must sit right of the channel spinbox"

    rx_ch, rx_lat = _cell(audio_grid, st.rx_channels), _cell(audio_grid, st.rx_latency)
    assert rx_ch[0] == rx_lat[0], "RX latency must share the RX Channels row"
    assert rx_lat[1] > rx_ch[1], "RX latency must sit right of the channel spinbox"
    assert rx_ch[0] > tx_ch[0], "RX row must sit below the TX row"

    # Hint label under the latency rows, exact spec wording.
    hint = _cell(audio_grid, st.latency_hint)
    assert hint[0] > rx_ch[0], "hint must sit under the latency rows"
    assert st.latency_hint.text() == HINT_TEXT

    # Two-column grid: one QGridLayout holds the columns on the content
    # widget; Actions and Config Files sit together in the right-column
    # stack (the container placed in the grid column right of the left
    # groups) with Actions above Config Files.
    actions_group = st.save_btn.parentWidget()
    config_group = st.asoundrc_btn.parentWidget()
    assert actions_group.title() == "Actions"
    assert config_group.title() == "Config Files"
    right_column = actions_group.parentWidget()
    content_grid = right_column.parentWidget().layout()
    assert isinstance(content_grid, QGridLayout), \
        f"content layout must be a QGridLayout, got {content_grid}"

    right_layout = right_column.layout()
    assert right_layout.indexOf(actions_group) < \
        right_layout.indexOf(config_group), \
        "Actions must sit above Config Files"

    right = _cell(content_grid, right_column)
    assert right[1] != -1, "right column container missing from the grid"

    # Left column: Network, Audio Parameters, Advanced — same column as each
    # other (and a different one than the right column), in the order
    # specified by the layout contract.
    net_group = st.iface_combo.parentWidget()
    adv_group = st.ptp_domain.parentWidget()
    net, aud, adv = (
        _cell(content_grid, g) for g in (net_group, audio_group, adv_group)
    )
    assert net[1] == aud[1] == adv[1], "left groups must share one column"
    assert net[1] != right[1], "left column must differ from the right column"
    assert net[0] < aud[0] < adv[0], \
        "left column order must be Network, Audio Parameters, Advanced"


def test_content_fits_standard_window_without_scroll(user_home, monkeypatch):
    """(g) The two-column content fits a 760x560 window without the
    fallback scroll area having to scroll."""
    st = _make_tab(monkeypatch, user_home)

    scroll = st.findChild(QScrollArea)
    assert scroll is not None, "the fallback scroll area must stay in place"

    sh = scroll.widget().sizeHint()
    assert sh.width() <= 760, \
        f"content too wide for a standard window: {sh.width()}px"
    assert sh.height() <= 560, \
        f"content too tall for a standard window: {sh.height()}px"
