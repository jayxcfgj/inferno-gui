# tests/test_raw_log_checkbox.py
"""Filtered-Checkbox: aus = Rohzeilen unverändert im Terminal (Level-Färbung),
an = gefilterte Anzeige. Parser läuft in beiden Modi weiter (Metriken/Status).
Rohmodus kürzt nicht und trimmt das Terminal auf _MAX_TERMINAL_LINES.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_raw_log_checkbox.py -v
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_filtered_checkbox_defaults_checked(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    assert ct.filtered_cb.text() == "Filtered"
    assert ct.filtered_cb.isChecked() is True


PLAIN = "2026-11-12T14:33:21.123456Z  TRACE statime::port: some raw trace detail"


def test_raw_mode_shows_plain_lines_verbatim(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    ct._process_log_output(PLAIN + "\n")
    assert PLAIN in ct.terminal_output.toPlainText()


def test_raw_mode_does_not_truncate_long_lines(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    long_line = "2026-11-12T14:33:21.123456Z TRACE a: " + "x" * 400
    ct._process_log_output(long_line + "\n")
    assert long_line in ct.terminal_output.toPlainText()   # alle 400 x


def test_filtered_mode_shows_summary_line(monkeypatch):
    """Positiv-Test: Im Default-Modus (Filtered an) wird eine Summary
    tatsächlich angezeigt - nicht nur Rohzeilen unterdrückt."""
    from test_lock_gate_wiring import _make_tab
    from test_log_parser import EST

    ct, _ = _make_tab(monkeypatch)
    ct._process_log_output(EST + "\n")
    text = ct.terminal_output.toPlainText()
    # Summary-Format (erste Zeile ist dank _last_summary_time = 0.0 sofort sichtbar)
    assert "offset=-123ns" in text
    assert "freq=1234ppb" in text
    assert "path_delay=4568ns" in text


def test_filtered_mode_hides_plain_lines(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._process_log_output(PLAIN + "\n")
    assert PLAIN not in ct.terminal_output.toPlainText()


def test_raw_mode_keeps_parser_updating(monkeypatch):
    from test_lock_gate_wiring import _make_tab
    from test_log_parser import EST

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    ct._process_log_output(EST + "\n")
    assert ct.parser.get_sync_status()['offset_ns'] is not None


def test_raw_mode_trims_terminal(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct.filtered_cb.setChecked(False)
    for i in range(3500):
        ct._process_log_output(f"raw line {i}\n")
    assert ct.terminal_output.document().blockCount() <= 3000   # _MAX_TERMINAL_LINES
