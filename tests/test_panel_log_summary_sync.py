# tests/test_panel_log_summary_sync.py
"""Panel-Log-Sync-Tests: Im gefilterten Modus koppeln Offset/Freq des
Status-Panels an die letzte ANGEZEIGTE Summary-Zeile (Log = Single Source
of Truth), nicht an die Live-Pending-Metriken, die bei jeder Zeile
mitlaufen und der Anzeige voraus sind. Im Rohmodus bleibt das Panel live
(dort wird jede Zeile angezeigt, live == Log). Das Lock-Gate bekommt
weiterhin die Live-Werte (Lockverhalten unveraendert).

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_panel_log_summary_sync.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inferno_gui.core.log_parser import StatimeLogParser

EST = ("2026-11-12T14:33:21.123456Z  TRACE statime::filters::kalman: "
       "Estimated offset -123.45ns+-12.3ns, freq 1.234+-0.567, delay 4567.8+-12.3")
EST_NEWER = ("2026-11-12T14:33:21.500000Z  TRACE statime::filters::kalman: "
             "Estimated offset -999.99ns+-12.3ns, freq 7.777+-0.567, delay 8888.8+-12.3")
TRANS_SLAVE = ("2026-11-12T14:33:22.123456Z  INFO statime::port: "
               "new state for port 0: Listening -> Slave")


# ── Parser-Ebene (reines Python, kein Qt) ─────────────────────────────

def test_get_last_summary_initially_none():
    p = StatimeLogParser()
    assert p.get_last_summary() is None


def test_last_summary_stays_at_displayed_summary_line():
    """Innerhalb des Filterintervalls erzeugte Zeilen aendern die letzte
    Summary nicht - das Panel soll die angezeigte Zeile spiegeln."""
    p = StatimeLogParser()
    e1 = p.parse_line(EST)                    # erste Zeile: sofort Summary
    assert e1 is not None and e1.offset_ns == -123
    p.parse_line(EST_NEWER)                   # innerhalb 1 s: keine neue Summary
    s = p.get_last_summary()
    assert s is not None and s.offset_ns == -123
    assert s.freq_ppb == 1234


def test_reset_all_clears_last_summary():
    p = StatimeLogParser()
    p.parse_line(EST)
    assert p.get_last_summary() is not None
    p.reset_all()
    assert p.get_last_summary() is None


# ── Panel-Ebene (Qt) ──────────────────────────────────────────────────

def test_filtered_panel_shows_summary_not_live(monkeypatch):
    """Gefiltert: Panel zeigt die Werte der letzten Summary-Zeile (-123),
    obwohl die Live-Metriken (-1000) bereits neuer sind."""
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.parser._last_summary_time = 0.0        # erste Zeile sofort anzeigen
    ct._process_log_output(EST + "\n")
    # Summary-Zeile steht im Log (Log == Panel)
    assert "offset=-123ns" in ct.terminal_output.toPlainText()
    # Neuere Messung innerhalb des 1-s-Filterintervalls: keine neue
    # Summary-Zeile, aber die Live-Metriken laufen mit.
    ct._process_log_output(EST_NEWER + "\n")
    s = ct.parser.get_sync_status()
    assert (s['offset_ns'], s['freq_ppb']) == (-1000, 7777)
    ct._update_status_panel()
    assert ct.ptp_offset_label.text() == "Offset: -123 ns"
    assert ct.ptp_freq_label.text() == "Freq: 1234 ppb"


def test_filtered_sync_light_uses_summary_offset(monkeypatch):
    """Gefiltert: Die Sync-Light-Schwellen nutzen den Summary-Offset; das
    State-Label bleibt bewusst live (State-Wechsel-Zeilen werden immer
    sofort angezeigt)."""
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.parser._last_summary_time = 0.0
    ct._process_log_output(EST + "\n")        # Summary: -123 ns
    ct._process_log_output(TRANS_SLAVE + "\n")  # State-Wechsel (live)
    ct._process_log_output(EST_NEWER + "\n")  # Live: -1000 ns
    ct._update_status_panel()
    assert ct.sync_label.text() == "Locked (123 ns)"      # Summary-Offset
    assert ct.ptp_offset_label.text() == "Offset: -123 ns"
    assert ct.ptp_state_label.text() == "State: Syncing..."  # Live-Offset -1000


def test_filtered_panel_without_summary_shows_dash(monkeypatch):
    """Noch keine Summary erzeugt und keine Live-Metriken (Rueckfall liefert
    hier ebenfalls None) -> Labels '—'."""
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    plain = ("2026-11-12T14:33:21.123456Z  TRACE statime::port: "
             "some raw trace detail")
    ct._process_log_output(plain + "\n")      # TRACE ohne Metriken, gefiltert
    ct._update_status_panel()
    assert ct.ptp_offset_label.text() == "Offset: —"
    assert ct.ptp_freq_label.text() == "Freq: —"


def test_raw_mode_panel_shows_live_values(monkeypatch):
    """Guard (bewusst sofort gruen-Richtung): Rohmodus zeigt jede Zeile -
    dort ist live == Log, das Panel zeigt die neuesten Werte."""
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    ct.parser._last_summary_time = 0.0
    ct._process_log_output(EST + "\n")
    ct._process_log_output(EST_NEWER + "\n")
    ct._update_status_panel()
    assert ct.ptp_offset_label.text() == "Offset: -1000 ns"
    assert ct.ptp_freq_label.text() == "Freq: 7777 ppb"
