"""Tests für den Statime Log-Parser (State-Übergänge + Severity, reines Python, kein Qt)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inferno_gui.core.log_parser import LogSeverity, StatimeLogParser

EST = ("2026-11-12T14:33:21.123456Z  TRACE statime::filters::kalman: "
       "Estimated offset -123.45ns+-12.3ns, freq 1.234+-0.567, delay 4567.8+-12.3")
TRANS_SLAVE = ("2026-11-12T14:33:22.123456Z  INFO statime::port: "
               "new state for port 0: Listening -> Slave")
TRANS_LISTEN = ("2026-11-12T14:33:30.123456Z  INFO statime::port: "
                "new state for port 0: Slave -> Listening")


def test_state_transition_parsed_uppercase():
    p = StatimeLogParser()
    e = p.parse_line(TRANS_SLAVE)
    assert e is not None and e.state == 'SLAVE'
    assert p.get_sync_status()['state'] == 'SLAVE'
    assert p._counters['state_changes'] == 1


def test_state_transition_clears_pending_metrics():
    p = StatimeLogParser()
    p.parse_line(EST)
    assert p.get_sync_status()['offset_ns'] is not None   # Fixture füllt Pending
    p.parse_line(TRANS_LISTEN)
    s = p.get_sync_status()
    assert s['state'] == 'LISTENING'
    assert s['offset_ns'] is None and s['freq_ppb'] is None and s['path_delay_ns'] is None


def test_no_state_inference_from_metrics():
    p = StatimeLogParser()
    p.parse_line(EST)
    assert p.get_sync_status()['state'] == 'UNKNOWN'      # keine SLAVE-Erfindung


def test_severity_from_level_prefix():
    p = StatimeLogParser()
    e = p.parse_line("2026-11-12T14:33:21.123456Z ERROR statime::clock: Could not adjust clock frequency")
    assert e.severity == LogSeverity.ERROR
    assert p._counters['errors'] == 1
    e2 = p.parse_line("2026-11-12T14:33:21.123456Z  WARN statime::port: Duplicate sync message")
    assert e2.severity == LogSeverity.WARNING
    assert p._counters['warnings'] == 1


def test_message_text_error_word_is_not_error():
    p = StatimeLogParser()
    e = p.parse_line("2026-11-12T14:33:21.123456Z TRACE statime::socket: could not parse packet: ParseError detail")
    assert e.severity == LogSeverity.INFO
    assert p._counters['errors'] == 0
