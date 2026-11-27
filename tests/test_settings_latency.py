"""Settings tab: RX/TX latency edit rows and the two-column layout.

Covers the latency-visualization Task 3 contract:
- defaults 10.0 ms, suffix " ms", 0.1 ms resolution, range 1.0–40.0
- .asoundrc ns ⇄ spinbox ms conversion on load/save, other keys survive
- clamp + warning tooltip + dynamic low-latency warning
- reset restores 10.0 ms; dirty tracking includes the spinboxes
- two-column QGridLayout: the Audio Parameters form groups the channel
  rows first, then the latency rows (TX Channels → RX Channels →
  TX Latency → RX Latency — never sharing a row), Actions and Config
  Files share the right column, and the content fits the user's 770x950
  window
  without the fallback scroll area needing to scroll — in the
  CONSTRUCTION state and with the Latency Overview POPULATED from a
  live PipeWire estimate (long real-world interface names in the
  combo included: neither the combo's longest item nor the
  overview's text lines may impose width).
- on wide/maximized windows the scroll content is capped (980px) and
  centered instead of stretching to the viewport: the right column
  stays strictly narrower than the left, no horizontal scrollbar
  appears at 1900px, and resizing back to the standard window
  changes nothing.
- compact layout for a 770px-logical viewport: the PTP version radios
  stack vertically (Network group ≤ 360px), the right column renders
  in the ~300–350px band (the 50:50 rebalance raises it from the
  squeezed ~240px cap), and the scroll content's minimum stays
  ≤ 720px so fat widget metrics still fit 770px without horizontal
  scrolling.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings_latency.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QGridLayout, QScrollArea, QFormLayout,
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

# A live PipeWire estimate as read_pipewire_latency() returns it
# (quantum 1024 @ 48000 Hz + headroom 128 → 24 ms per direction,
# 48 ms round trip).
PW_SAMPLE = {
    "quantum": 1024,
    "rate": 48000,
    "headroom": 128,
    "per_direction_ms": 24.0,
    "round_trip_ms": 48.0,
    "source": "pw-metadata",
}

# Interface names as they appear on real machines (bridges, USB and
# WiFi adapters): their display strings are the longest the combo ever
# holds and must not dictate the group width.
LONG_IFACES = [
    "br-099035d51c18", "docker0", "enx6c6e07057ee0", "wlxdc4ef407eb05",
]
LONG_IFACE_IPS = {
    "br-099035d51c18": "192.168.1.100",
    "docker0": "172.17.0.1",
    "enx6c6e07057ee0": "192.168.178.42",
    "wlxdc4ef407eb05": "192.168.178.23",
}


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
    # BIND_IP follows the selected interface's current IP (production
    # DHCP fix — see tests/test_bind_ip_sync.py): the fixture's stale
    # 192.168.1.10 is replaced by the fake eth0's 10.0.0.1
    assert 'BIND_IP "10.0.0.1"' in content, content


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


def test_running_state_locks_latency_spinboxes(user_home, monkeypatch):
    """(m) While inferno runs, both latency spinboxes lock (like the
    channels — latency only takes effect after the next PTP start
    anyway); stopping re-enables them.  log_level stays locked in
    every state (trace lock, Task-6)."""
    st = _make_tab(monkeypatch, user_home)

    assert st.rx_latency.isEnabled() is True
    assert st.tx_latency.isEnabled() is True

    st.set_running_state(True)
    assert st.rx_latency.isEnabled() is False, \
        "running must lock the RX latency spinbox"
    assert st.tx_latency.isEnabled() is False, \
        "running must lock the TX latency spinbox"
    assert st.log_level.isEnabled() is False, \
        "log_level must stay locked while running"

    st.set_running_state(False)
    assert st.rx_latency.isEnabled() is True, \
        "stopping must re-enable the RX latency spinbox"
    assert st.tx_latency.isEnabled() is True, \
        "stopping must re-enable the TX latency spinbox"
    assert st.log_level.isEnabled() is False, \
        "log_level must stay locked while stopped"


def _cell(grid, widget):
    """(row, column, rowSpan, colSpan) of a widget inside a QGridLayout."""
    return grid.getItemPosition(grid.indexOf(widget))


def test_two_column_grid_structure(user_home, monkeypatch):
    """(f) Audio Parameters groups the channel rows first, then the
    latency rows — TX Channels → RX Channels → TX Latency → RX Latency,
    each on its OWN row (they must NOT share a row with anything; the
    label order keeps the pairing readable).  The groups form a
    two-column grid (left: Network/Audio/Advanced; right: Actions above
    Config Files)."""
    st = _make_tab(monkeypatch, user_home)

    # Audio Parameters is a QFormLayout of plain rows; channels group
    # first, then the latencies, none sharing a row.
    audio_group = st.tx_channels.parentWidget()
    audio_form = audio_group.layout()
    assert isinstance(audio_form, QFormLayout), \
        f"Audio Parameters must be a QFormLayout, got {audio_form}"

    def _row(widget):
        return audio_form.getWidgetPosition(widget)[0]

    tx_ch, tx_lat = _row(st.tx_channels), _row(st.tx_latency)
    rx_ch, rx_lat = _row(st.rx_channels), _row(st.rx_latency)
    assert tx_ch != tx_lat, "TX latency must NOT share the TX Channels row"
    assert rx_ch != rx_lat, "RX latency must NOT share the RX Channels row"
    # channels adjacent, latencies adjacent, latencies AFTER channels
    assert tx_ch < rx_ch, "channel rows keep the TX → RX order"
    assert rx_ch == tx_ch + 1, \
        "the channel rows must sit adjacent (TX Channels → RX Channels)"
    assert tx_lat == rx_ch + 1, \
        "TX Latency must sit directly below the channel rows"
    assert rx_lat == tx_lat + 1, \
        "the latency rows must sit adjacent (TX Latency → RX Latency)"
    assert tx_lat > rx_ch, \
        "the latency rows must come after the channel rows"

    # Device Name and Sample Rate lead the form.
    assert _row(st.device_name) < _row(st.sample_rate) < tx_ch, \
        "form must lead with Device Name, then Sample Rate"

    # Hint label under the rows, exact spec wording.
    assert _row(st.latency_hint) > rx_lat, \
        "hint must sit under the latency rows"
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


def test_content_fits_user_window_without_scroll(user_home, monkeypatch):
    """(g) The two-column content stays within the compact budgets —
    sizeHint width ≤ 760, height ≤ 700 — so the user's 770x950 window
    holds the tab without the fallback scroll area scrolling.  (The
    stacked latency rows cost ~2 rows of height; ~700 leaves a wide
    margin under the ~800px usable height of the 950-970-logical
    window.)"""
    st = _make_tab(monkeypatch, user_home)

    scroll = st.findChild(QScrollArea)
    assert scroll is not None, "the fallback scroll area must stay in place"

    sh = scroll.widget().sizeHint()
    assert sh.width() <= 760, \
        f"content too wide for a standard window: {sh.width()}px"
    assert sh.height() <= 700, \
        f"content too tall for the user's window: {sh.height()}px"


def test_populated_latency_overview_fits_without_horizontal_scroll(
        user_home, monkeypatch):
    """(h) The populated state fits 760px too: with a live PipeWire
    estimate in the Latency Overview and long real-world interface
    names in the combo, neither the overview's text lines nor the
    combo's longest item may impose width on the scroll content
    (no horizontal scrollbar at the standard window size)."""
    import inferno_gui.ui.settings_tab as settings_tab

    _fake_interfaces(monkeypatch, LONG_IFACES, LONG_IFACE_IPS)
    monkeypatch.setattr(
        settings_tab, "read_pipewire_latency", lambda: PW_SAMPLE)

    st = settings_tab.SettingsTab()
    _ensure_app().processEvents()
    st.show()
    _ensure_app().processEvents()
    st._refresh_latency_overview()
    _ensure_app().processEvents()

    # Guard against a false pass: the overview must really be
    # populated from the patched estimate.
    assert st.latency_bar.total_text() == \
        "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)", \
        st.latency_bar.total_text()
    assert st.latency_bar.hint_text() == \
        "estimated — quantum 1024 @ 48000 Hz + headroom 128", \
        st.latency_bar.hint_text()

    scroll = st.findChild(QScrollArea)
    content = scroll.widget()
    min_w = content.minimumSizeHint().width()
    hint_w = content.sizeHint().width()
    assert min_w <= 760, \
        f"populated content minimum too wide: {min_w}px"
    assert hint_w <= 760, \
        f"populated content too wide: {hint_w}px"

    st.hide()


def test_wide_window_caps_content_and_keeps_right_column_narrower(
        user_home, monkeypatch):
    """(i) A wide/maximized window must not stretch the two-column
    content to the viewport: the scroll content stays within its
    980px cap, the right column (Latency Overview) stays strictly
    NARROWER than the left column (Network Interface), and no
    horizontal scrollbar appears; resizing back to the standard
    760x560 leaves the construction behavior untouched (no horizontal
    scrollbar there either)."""
    import inferno_gui.ui.settings_tab as settings_tab

    _fake_interfaces(monkeypatch, LONG_IFACES, LONG_IFACE_IPS)
    monkeypatch.setattr(
        settings_tab, "read_pipewire_latency", lambda: PW_SAMPLE)

    st = settings_tab.SettingsTab()
    _ensure_app().processEvents()
    st.show()
    _ensure_app().processEvents()
    st._refresh_latency_overview()
    _ensure_app().processEvents()

    # Guard against a false pass: the overview must really be
    # populated from the patched estimate (the populated state is the
    # widest the right column ever gets).
    assert st.latency_bar.total_text() == \
        "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)", \
        st.latency_bar.total_text()

    scroll = st.findChild(QScrollArea)
    content = scroll.widget()
    net_group = st.iface_combo.parentWidget()
    latency_group = st.latency_bar.parentWidget()

    # Wide/maximized window (1900x900).
    st.resize(1900, 900)
    _ensure_app().processEvents()
    _ensure_app().processEvents()

    assert content.width() <= 980, \
        f"scroll content stretched to {content.width()}px on a wide window"
    assert latency_group.width() < net_group.width(), (
        f"right column ({latency_group.width()}px) must stay narrower "
        f"than the left column ({net_group.width()}px) on a wide window")
    assert scroll.horizontalScrollBar().maximum() == 0, \
        "horizontal scrollbar appeared at 1900px"

    # Standard window (760x560): resizing back changes nothing.
    st.resize(760, 560)
    _ensure_app().processEvents()
    _ensure_app().processEvents()
    assert scroll.horizontalScrollBar().maximum() == 0, \
        "horizontal scrollbar appeared after resizing back to 760x560"

    st.hide()


def test_ptp_version_radios_stacked_and_net_group_narrow(
        user_home, monkeypatch):
    """(j) The two PTP version radios stack vertically (side by side
    they forced the Network Interface group to a 467px minimum); the
    stacked group fits the 360px compact budget the 770px-viewport
    layout needs."""
    from PyQt6.QtWidgets import QVBoxLayout

    st = _make_tab(monkeypatch, user_home)

    # The radios share one nested sub-layout of the Network form, and
    # that sub-layout is a vertical box (QFormLayout wraps a sub-layout
    # passed to addRow; the radio widgets stay children of the group).
    v1, v2 = st.ptp_v1_radio, st.ptp_v2_radio
    net_form = st.iface_combo.parentWidget().layout()
    radio_layout = None
    for i in range(net_form.count()):
        item = net_form.itemAt(i)
        sub = item.layout() if item is not None else None
        if sub is not None and sub.indexOf(v1) != -1 and sub.indexOf(v2) != -1:
            radio_layout = sub
            break
    assert radio_layout is not None, \
        "no single sub-layout holds both PTP radios"
    assert isinstance(radio_layout, QVBoxLayout), \
        f"PTP radios must be stacked in a QVBoxLayout, got {radio_layout}"

    # Rendered geometry: PTPv2 sits fully below PTPv1 (not beside it).
    st.show()
    _ensure_app().processEvents()
    assert v2.y() >= v1.y() + v1.height(), (
        f"PTPv2 must sit below PTPv1: "
        f"v1 y={v1.y()} height={v1.height()}, v2 y={v2.y()}")
    st.hide()

    net_group = st.iface_combo.parentWidget()
    net_min = net_group.minimumSizeHint().width()
    assert net_min <= 360, \
        f"Network group minimum {net_min}px exceeds the 360px budget " \
        "(the stacked radios alone must not leave the combo floor above it)"


def test_right_column_50_50_on_wide_windows(user_home, monkeypatch):
    """(k) The right column (Latency Overview / Actions / Config Files)
    gets its ~50:50 share back: its container's minimum stays
    ≤ 350px and a 1900px window renders it strictly inside the
    300–350px band (the old 240px cap squeezed it; the old 3:2
    stretch alone rendered it 382px)."""
    import inferno_gui.ui.settings_tab as settings_tab

    _fake_interfaces(monkeypatch, LONG_IFACES, LONG_IFACE_IPS)
    monkeypatch.setattr(
        settings_tab, "read_pipewire_latency", lambda: PW_SAMPLE)

    st = settings_tab.SettingsTab()
    _ensure_app().processEvents()

    actions_group = st.save_btn.parentWidget()
    right_column = actions_group.parentWidget()
    assert right_column.minimumSizeHint().width() <= 350, \
        (f"right column minimum {right_column.minimumSizeHint().width()}px "
         "exceeds the 350px budget")

    st.show()
    _ensure_app().processEvents()
    st._refresh_latency_overview()
    _ensure_app().processEvents()

    # Guard against a false pass: the populated overview is the widest
    # the right column ever gets.
    assert st.latency_bar.total_text() == \
        "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)", \
        st.latency_bar.total_text()

    st.resize(1900, 900)
    _ensure_app().processEvents()
    _ensure_app().processEvents()
    rw = right_column.width()
    assert 300 <= rw <= 350, (
        f"right column rendered {rw}px on a wide window; it must sit in "
        "the ~300–350px band of the 50:50 rebalance")

    st.hide()


def test_compact_content_fits_770_viewport(user_home, monkeypatch):
    """(l) Compact-layout budget: the scroll content's minimum stays
    ≤ 720px (offscreen metrics) so the user's 770px-logical viewport
    holds the tab without scrolling even with fat widget metrics —
    in the CONSTRUCTION state and with the overview POPULATED, and
    nothing clips at 770x950 (no scrollbar either way)."""
    import inferno_gui.ui.settings_tab as settings_tab

    # Construction state.
    st = _make_tab(monkeypatch, user_home)
    scroll = st.findChild(QScrollArea)
    content = scroll.widget()
    con_min = content.minimumSizeHint().width()
    assert con_min <= 720, \
        f"construction content minimum {con_min}px exceeds the 720px budget"

    # Populated state: long interfaces in the combo and a live
    # PipeWire estimate in the overview.
    _fake_interfaces(monkeypatch, LONG_IFACES, LONG_IFACE_IPS)
    monkeypatch.setattr(
        settings_tab, "read_pipewire_latency", lambda: PW_SAMPLE)

    st2 = settings_tab.SettingsTab()
    _ensure_app().processEvents()
    st2.show()
    _ensure_app().processEvents()
    st2._refresh_latency_overview()
    _ensure_app().processEvents()

    assert st2.latency_bar.total_text() == \
        "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)", \
        st2.latency_bar.total_text()

    scroll2 = st2.findChild(QScrollArea)
    content2 = scroll2.widget()
    pop_min = content2.minimumSizeHint().width()
    assert pop_min <= 720, \
        f"populated content minimum {pop_min}px exceeds the 720px budget"

    # Nothing clipped at the 770x950 viewport: no scrollbar in either
    # direction (the stacked latency rows must stay short enough that
    # the user's tall window never grows a vertical one).
    st2.resize(770, 950)
    _ensure_app().processEvents()
    _ensure_app().processEvents()
    assert scroll2.horizontalScrollBar().maximum() == 0, \
        "horizontal scrollbar appeared at the 770x950 viewport"
    assert scroll2.verticalScrollBar().maximum() == 0, \
        "vertical scrollbar appeared at the 770x950 viewport"

    st2.hide()
