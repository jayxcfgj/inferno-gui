# tests/test_sync_state.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inferno_gui.core.sync_state import display_state, light_color, tray_state


def test_display_state_table():
    cases = [
        # (raw_state, offset_ns, expected)
        ("MASTER", None, "Grand Master"),
        ("MASTER", 0, "Grand Master"),
        ("FAULTY", None, "FAULTY"),
        ("FAULTY", 5, "FAULTY"),
        ("LISTENING", None, "Listening..."),
        ("PASSIVE", None, "Listening..."),
        ("UNCALIBRATED", None, "Uncalibrated"),
        ("UNCALIBRATED", 5, "Uncalibrated"),
        ("SLAVE", None, "Initializing..."),
        ("SLAVE", 0, "Locked"),
        ("SLAVE", 199, "Locked"),
        ("SLAVE", 200, "Locked"),       # boundary: |offset| <= 200
        ("SLAVE", -200, "Locked"),
        ("SLAVE", 201, "Syncing..."),   # boundary: 201
        ("SLAVE", -201, "Syncing..."),
        ("SLAVE", 999, "Syncing..."),
        ("SLAVE", 1000, "Syncing..."),  # boundary: <= 1000
        ("SLAVE", -1000, "Syncing..."),
        ("SLAVE", 1001, "Uncalibrated"),  # boundary: 1001
        ("SLAVE", -1001, "Uncalibrated"),
        (None, None, "Initializing..."),
        (None, 100, "Initializing..."),
        ("WHATEVER", None, "Initializing..."),
        ("", 0, "Initializing..."),
    ]
    for raw_state, offset_ns, expected in cases:
        assert display_state(raw_state, offset_ns) == expected, (
            f"display_state({raw_state!r}, {offset_ns!r}) != {expected!r}"
        )

def test_light_color_table():
    cases = [
        ("MASTER", None, "#2196F3"),
        ("MASTER", 0, "#2196F3"),
        ("FAULTY", None, "#f44336"),
        ("LISTENING", None, "gray"),
        ("PASSIVE", None, "gray"),
        (None, None, "gray"),
        ("WHATEVER", None, "gray"),
        ("SLAVE", None, "gray"),
        ("UNCALIBRATED", None, "orange"),
        ("SLAVE", 0, "#4caf50"),
        ("SLAVE", 200, "#4caf50"),      # boundary: locked
        ("SLAVE", -200, "#4caf50"),
        ("SLAVE", 201, "#ffc107"),      # boundary: syncing
        ("SLAVE", 1000, "#ffc107"),
        ("SLAVE", -1000, "#ffc107"),
        ("SLAVE", 1001, "#f44336"),     # boundary: beyond syncing
        ("SLAVE", -1001, "#f44336"),
    ]
    for raw_state, offset_ns, expected in cases:
        assert light_color(raw_state, offset_ns) == expected, (
            f"light_color({raw_state!r}, {offset_ns!r}) != {expected!r}"
        )

def test_tray_state_table():
    cases = [
        ("SLAVE", 0, "green"),
        ("SLAVE", 200, "green"),        # boundary: locked
        ("SLAVE", -200, "green"),
        ("SLAVE", 201, "yellow"),       # boundary: syncing
        ("SLAVE", 1000, "yellow"),
        ("SLAVE", -1000, "yellow"),
        ("SLAVE", 1001, "black"),       # boundary: beyond syncing
        ("SLAVE", None, "black"),
        ("FAULTY", None, "black"),
        ("MASTER", 0, "black"),
        ("LISTENING", None, "black"),
        ("PASSIVE", None, "black"),
        ("UNCALIBRATED", None, "black"),
        (None, None, "black"),
        ("WHATEVER", None, "black"),
    ]
    for raw_state, offset_ns, expected in cases:
        assert tray_state(raw_state, offset_ns) == expected, (
            f"tray_state({raw_state!r}, {offset_ns!r}) != {expected!r}"
        )
