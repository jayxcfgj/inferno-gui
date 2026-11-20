"""Latency Overview: bar segments, unknown case, settings-tab wiring.

Covers the latency-visualization Task 4 contract plus the final-review
fixes:
- set_values(10.0, 48.0): two segments with proportional widths
  (segment fractions exposed as attributes) and the total line
  "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)"
- set_values(10.0, None): PipeWire segment absent; honest total
  "Total unknown (Inferno RX 10.0 ms + PipeWire: unknown)"
- details dict (quantum/rate/headroom): compact visible line
  "estimated — quantum 1024 @ 48000 Hz + headroom 128"; the full scope
  ("... — excludes hardware DAC/ADC latency") rides the tooltip
  (a full visible line would exceed the right-column width budget)
- settings tab: the Latency Overview group is the FIRST widget of the
  right column (above Actions) and carries the verbatim honesty tooltip
- construction does NOT query PipeWire (M5); showEvent triggers
  read_pipewire_latency (patched) and updates the text; the no-node
  case shows "unknown" without crashing
- extreme scaling: 10 vs 0.5 ms keeps both segments visible via the
  minimum-width floor; zero values never divide by zero

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_latency_overview.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import QApplication

# Hold a module-level reference: a temporary QApplication() expression is
# garbage-collected immediately, which aborts later widget construction.
_app = QApplication.instance() or QApplication(sys.argv)

# Verbatim honesty note (user-approved wording).
HONESTY_NOTE = (
    "Inferno currently advertises RX and applies TX on receive — "
    "upstream FIXME; values shown are the configured ones."
)

PW_SAMPLE = {
    "quantum": 1024,
    "rate": 48000,
    "headroom": 128,
    "per_direction_ms": 24.0,
    "round_trip_ms": 48.0,
    "source": "pw-metadata",
}


def _ensure_app() -> QApplication:
    return _app


def _fake_interfaces(monkeypatch, ifaces, ips=None):
    """Force the detected interface list and IPs (pattern from
    tests/test_settings_latency.py)."""
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


def _make_tab(monkeypatch, home, pw_result=None):
    """Build a SettingsTab against the fake home with pw-metadata
    patched, so no test shells out to the real PipeWire."""
    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "10.0.0.1"})
    import inferno_gui.ui.settings_tab as settings_tab
    monkeypatch.setattr(
        settings_tab, "read_pipewire_latency", lambda: pw_result)
    st = settings_tab.SettingsTab()
    _ensure_app().processEvents()
    return st


# ── LatencyBar unit behaviour ────────────────────────────────


def test_set_values_two_segments_proportional_and_total_text():
    """(a) 10 + 48: proportional segment fractions and the total line
    labelling the PipeWire share as a round-trip estimate."""
    from inferno_gui.ui.latency_overview import LatencyBar
    bar = LatencyBar()
    bar.set_values(10.0, 48.0)

    assert bar.inferno_fraction == pytest.approx(10.0 / 58.0)
    assert bar.pipewire_fraction == pytest.approx(48.0 / 58.0)
    # proportional pixel widths: 580px splits 10:48 exactly into 100:480
    assert bar.segment_widths(580) == (100, 480)

    assert bar.total_text() == \
        "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)"
    # visible text must say "round-trip" and "estimated" (I2)
    assert "round-trip" in bar.total_text()
    assert "estimated" in bar.hint_text()


def test_set_values_backward_compatible_two_args():
    """I2: the pre-details two-argument call keeps working."""
    from inferno_gui.ui.latency_overview import LatencyBar
    bar = LatencyBar()
    bar.set_values(10.0, 48.0)  # no details → must not raise

    assert bar.total_text() == \
        "Total ≈ 58.0 ms (Inferno 10.0 + PipeWire round-trip ≈ 48.0)"
    assert bar.hint_text() == \
        "estimated — PipeWire round-trip from the current quantum"


def test_details_surface_quantum_and_scope_disclosure():
    """I2: the details dict surfaces quantum/rate/headroom in a compact
    visible line; the full scope text — including the hardware
    DAC/ADC exclusion — rides the tooltip (a full visible line would
    exceed the right-column width budget at 760px)."""
    from inferno_gui.ui.latency_overview import LatencyBar
    bar = LatencyBar()
    bar.set_values(10.0, 48.0, details=PW_SAMPLE)

    # compact visible details line
    assert bar.hint_text() == \
        "estimated — quantum 1024 @ 48000 Hz + headroom 128"

    # full disclosure in the tooltip
    tip = bar.toolTip()
    assert "quantum 1024 @ 48000 Hz + headroom 128" in tip
    assert "excludes hardware DAC/ADC latency" in tip
    assert "round-trip" in tip


def test_set_values_unknown_pipewire_segment_absent():
    """(b) PipeWire None: segment absent, inferno spans the bar, and
    the total stays honest — "unknown", never a numerical total built
    on a missing component (I3)."""
    from inferno_gui.ui.latency_overview import LatencyBar
    bar = LatencyBar()
    bar.set_values(10.0, None)

    assert bar.pipewire_fraction == 0.0
    assert bar.inferno_fraction == 1.0
    assert bar.segment_widths(580) == (580, 0)

    assert bar.total_text() == \
        "Total unknown (Inferno RX 10.0 ms + PipeWire: unknown)"
    assert "unknown" in bar.hint_text()
    # no fake total: the numerical part belongs to Inferno only
    assert "Total ≈" not in bar.total_text()


def test_extreme_scaling_floor_and_no_division_by_zero():
    """(e) 10 vs 0.5 ms: both segments stay visible via the minimum-
    width floor; degenerate zero values must not divide by zero."""
    from inferno_gui.ui.latency_overview import LatencyBar
    bar = LatencyBar()
    bar.set_values(10.0, 0.5)

    # at 60px the 0.5 ms share would be ~3px proportionally — the floor
    # must keep both segments visible while preserving the bar width.
    iw, pw = bar.segment_widths(60)
    assert iw > 0 and pw > 0
    assert iw + pw == 60
    assert pw >= 8, "tiny-but-positive shares must stay visible"

    # degenerate values: no ZeroDivisionError, nothing painted
    bar.set_values(0.0, None)
    assert bar.segment_widths(580) == (0, 0)
    bar.set_values(0.0, 0.0)
    assert bar.segment_widths(580) == (0, 0)


# ── Settings tab integration ─────────────────────────────────


def test_overview_group_first_in_right_column(user_home, monkeypatch):
    """(c) The Latency Overview group sits at the top of the right
    column, above Actions, and carries the verbatim honesty tooltip."""
    st = _make_tab(monkeypatch, user_home)

    right_layout = st.save_btn.parentWidget().parentWidget().layout()
    first = right_layout.itemAt(0).widget()
    assert first.title() == "Latency Overview"
    actions_group = st.save_btn.parentWidget()
    assert right_layout.indexOf(first) < right_layout.indexOf(actions_group)

    assert st.latency_bar.parentWidget() is first
    assert HONESTY_NOTE in first.toolTip()


def test_construction_does_not_query_pipewire(user_home, monkeypatch):
    """(M5) No synchronous pw-metadata query at construction time (it
    cost up to 2 s before the tab was ever shown); the first showEvent
    handles the first paint."""
    import inferno_gui.ui.settings_tab as settings_tab
    calls = []

    def fake_read():
        calls.append(1)
        return PW_SAMPLE

    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "10.0.0.1"})
    monkeypatch.setattr(settings_tab, "read_pipewire_latency", fake_read)
    st = settings_tab.SettingsTab()
    _ensure_app().processEvents()

    assert calls == [], "construction must not shell out to pw-metadata"

    st.show()
    _ensure_app().processEvents()
    assert calls == [1], "first showEvent must trigger the query"
    st.hide()


def test_show_event_refreshes_latency_overview(user_home, monkeypatch):
    """(d) showEvent calls read_pipewire_latency (patched) and repaints;
    the no-node case shows "unknown" without crashing; the Inferno
    segment follows the RX spinbox, not TX; the estimate's scope
    (round-trip, quantum/rate/headroom, DAC/ADC exclusion) is
    disclosed (I2) and the honesty note stays on the bar tooltip."""
    import inferno_gui.ui.settings_tab as settings_tab
    state = {"pw": None, "calls": 0}

    def fake_read():
        state["calls"] += 1
        return state["pw"]

    _fake_interfaces(monkeypatch, ["eth0"], {"eth0": "10.0.0.1"})
    monkeypatch.setattr(settings_tab, "read_pipewire_latency", fake_read)
    st = settings_tab.SettingsTab()
    _ensure_app().processEvents()

    # (M5) construction must NOT have queried; the bar still shows its
    # placeholder until the first showEvent paints it.
    assert state["calls"] == 0
    assert st.latency_bar.total_text() == "—"

    # showEvent must run the helper; no PipeWire node → honest unknown,
    # no crash
    calls_before = state["calls"]
    st.show()
    _ensure_app().processEvents()
    assert state["calls"] > calls_before
    assert st.latency_bar.total_text() == \
        "Total unknown (Inferno RX 10.0 ms + PipeWire: unknown)"

    # a live estimate updates the text; the Inferno segment follows RX
    st.rx_latency.setValue(20.0)
    st.tx_latency.setValue(35.0)  # must NOT leak into the total line
    state["pw"] = PW_SAMPLE
    st.hide()
    st.show()
    _ensure_app().processEvents()
    assert st.latency_bar.total_text() == \
        "Total ≈ 68.0 ms (Inferno 20.0 + PipeWire round-trip ≈ 48.0)"

    # (I2) the estimate's scope is disclosed: compact visible details
    # plus the full text (DAC/ADC exclusion) in the tooltip, alongside
    # the tab's honesty note.
    assert st.latency_bar.hint_text() == \
        "estimated — quantum 1024 @ 48000 Hz + headroom 128"
    tip = st.latency_bar.toolTip()
    assert "excludes hardware DAC/ADC latency" in tip
    assert HONESTY_NOTE in tip
    st.hide()
