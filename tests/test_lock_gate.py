# tests/test_lock_gate.py
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inferno_gui.core.lock_gate import LockGate


def test_lock_after_five_stable_ticks():
    g = LockGate(threshold_ns=1000, required_ticks=5)
    for _ in range(4):
        assert g.feed('SLAVE', 500) is False
    assert g.feed('SLAVE', 500) is True
    assert g.stable_count == 5

def test_interrupt_resets_counter():
    g = LockGate(1000, 5)
    for _ in range(3):
        g.feed('SLAVE', 500)
    assert g.feed('LISTENING', None) is False      # State-Wechsel
    assert g.stable_count == 0
    for _ in range(4):
        assert g.feed('SLAVE', 999) is False
    assert g.feed('SLAVE', 999) is True

def test_offset_none_is_no_hit():
    g = LockGate(1000, 5)
    assert g.feed('SLAVE', None) is False
    assert g.stable_count == 0

def test_offset_above_threshold_is_no_hit():
    g = LockGate(1000, 5)
    assert g.feed('SLAVE', 1001) is False
    assert g.stable_count == 0

def test_threshold_is_inclusive():
    g = LockGate(1000, 1)
    assert g.feed('SLAVE', 1000) is True

def test_reset_clears_state():
    g = LockGate(1000, 5)
    for _ in range(5):
        g.feed('SLAVE', 100)
    g.reset()
    assert g.stable_count == 0
    assert g.feed('SLAVE', 100) is False
