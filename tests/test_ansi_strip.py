# tests/test_ansi_strip.py
"""ANSI-Strip-Tests: statime schreibt ANSI-Escape-Sequenzen (Farbcodes) in
seinen Stream. Die duerfen weder 1:1 im Terminal landen noch den Severity-
Regex des Parsers zerstoeren (sonst wird eine ERROR-Zeile zu INFO und der
errors-Zaehler bleibt 0). Strip passiert in _process_log_output - NICHT beim
Empfang (_on_stdout/_on_stderr), weil eine Escape-Sequenz ueber zwei
50-ms-Chunks gesplittet sein kann; _flush_terminal liefert dort garantiert
komplette Zeilen, ueber die eine Escape-Sequenz nicht ueberspannen kann.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_ansi_strip.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ANSI_PLAIN = ("\x1b[2m2026-11-12T14:33:21.123456Z\x1b[0m  \x1b[35mTRACE\x1b[0m "
              "statime::port: some raw trace detail")
ANSI_ERROR = ("\x1b[2m2026-11-12T14:33:21.123456Z\x1b[0m \x1b[31mERROR\x1b[0m "
              "statime::clock: Could not adjust clock frequency")
ANSI_EST = ("\x1b[2m2026-11-12T14:33:21.123456Z\x1b[0m  \x1b[35mTRACE\x1b[0m "
            "statime::filters::kalman: Estimated offset -123.45ns+-12.3ns, "
            "freq 1.234+-0.567, delay 4567.8+-12.3")


def test_raw_mode_strips_ansi_sequences(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    ct._process_log_output(ANSI_PLAIN + "\n")
    text = ct.terminal_output.toPlainText()
    assert "\x1b" not in text, "no ANSI escape may reach the terminal"
    assert "some raw trace detail" in text


def test_filtered_mode_ansi_error_counts_and_shown(monkeypatch):
    """Ohne Strip matcht der Severity-Regex die ANSI-Zeile nicht -> ERROR
    wird INFO (Zaehler 0) und im gefilterten Modus verschluckt."""
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._process_log_output(ANSI_ERROR + "\n")
    assert ct.parser.get_sync_status()['errors'] == 1
    assert "Could not adjust clock frequency" in ct.terminal_output.toPlainText()


def test_filtered_mode_ansi_est_metrics_parsed(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._process_log_output(ANSI_EST + "\n")
    s = ct.parser.get_sync_status()
    assert s['offset_ns'] == -123
    assert s['freq_ppb'] == 1234
    assert s['path_delay_ns'] == 4568


def test_escape_split_across_chunks_survives_via_flush(monkeypatch):
    """Escape-Sequenz ueber zwei 50-ms-Chunks gesplittet: _flush_terminal
    haelt das Fragment im Puffer, erst die vervollstaendigte Zeile wird
    gestrippt - im Terminal landet trotzdem kein \\x1b."""
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    head, tail = ANSI_PLAIN[:30], ANSI_PLAIN[30:]
    assert "\x1b" in head and "\x1b" in tail   # Split mitten in der Sequenz
    ct._stdout_buffer = head
    ct._flush_terminal()
    ct._stdout_buffer = tail + "\n"
    ct._flush_terminal()
    text = ct.terminal_output.toPlainText()
    assert "\x1b" not in text
    assert "some raw trace detail" in text
