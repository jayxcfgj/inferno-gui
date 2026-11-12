# tests/test_log_output_split.py
"""Split-Line-Puffer-Tests: unvollstaendige Zeilen-Reste (ohne \\n)
duerfen bei 50-ms-Flushes NICHT als eigene (zerstoerte) Zeilen in den
Parser laufen - sie bleiben im Puffer, bis sie durch nachfolgende
Chunks vervollstaendigt werden. Erst ueber 8192 Zeichen ohne Newline
wird forciert verarbeitet.

Run: QT_QPA_PLATFORM=offscreen /tmp/opencode/inferno-dev/bin/pytest tests/test_log_output_split.py -q
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_partial_line_kept_in_buffer(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    partial = "2026-11-12T00:00:00.000000Z ERROR a: partial"
    ct._stdout_buffer = partial
    ct._flush_terminal()
    assert partial not in ct.terminal_output.toPlainText()
    assert ct._stdout_buffer == partial
    assert not ct._write_timer.isActive()


def test_complete_lines_processed_residue_kept(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._stdout_buffer = (
        "2026-11-12T00:00:00.000000Z ERROR a: boom\n"
        "2026-11-12T00:00:01.000000Z ERROR b: part"
    )
    ct._flush_terminal()
    text = ct.terminal_output.toPlainText()
    assert "boom" in text                       # komplette Zeile verarbeitet
    assert "part" not in text                   # Fragment NICHT als eigene Zeile
    assert ct._stdout_buffer == "2026-11-12T00:00:01.000000Z ERROR b: part"


def test_residue_completes_on_next_flush(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._stdout_buffer = "2026-11-12T00:00:00.000000Z ERROR a: par"
    ct._flush_terminal()
    ct._stdout_buffer += "tial done\n2026-11-12T00:00:02.000000Z ERROR c: next\n"
    ct._flush_terminal()
    text = ct.terminal_output.toPlainText()
    assert "partial done" in text               # über Flusses hinweg zusammengesetzt
    assert "next" in text
    assert ct._stdout_buffer == ""


def test_forced_flush_over_8kb_without_newline(monkeypatch):
    from test_lock_gate_wiring import _make_tab

    ct, _ = _make_tab(monkeypatch)
    ct._stdout_buffer = "x" * 9000              # nie `\n` → trotzdem leeren
    ct._flush_terminal()
    assert ct._stdout_buffer == ""
