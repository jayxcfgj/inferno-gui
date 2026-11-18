"""Pure Sync-Zustands-Mapping: Display-Text, Ampel-Farbe und Tray-Farbe.

Keine Qt-Abhaengigkeiten - die Funktionen sind komplett testbar ohne UI.
Aufgabe der Single Source of Truth fuer Sync-Status in UI und Log-Parser.
"""

from __future__ import annotations

LOCKED_MAX_NS = 200
SYNCING_MAX_NS = 1000

_DISPLAY_FOR_STATE = {
    'MASTER': 'Grand Master',
    'FAULTY': 'FAULTY',
    'LISTENING': 'Listening...',
    'PASSIVE': 'Listening...',
    'UNCALIBRATED': 'Uncalibrated',
}

_COLOR_FOR_STATE = {
    'MASTER': '#2196F3',
    'FAULTY': '#f44336',
    'LISTENING': 'gray',
    'PASSIVE': 'gray',
    'UNCALIBRATED': 'orange',
}


def display_state(raw_state: str | None, offset_ns: int | None) -> str:
    """Menschlich lesbaren Sync-Status fuer die UI ableiten."""
    if raw_state in _DISPLAY_FOR_STATE:
        return _DISPLAY_FOR_STATE[raw_state]
    if raw_state == 'SLAVE':
        if offset_ns is None:
            return 'Initializing...'
        offset = abs(offset_ns)
        if offset <= LOCKED_MAX_NS:
            return 'Locked'
        if offset <= SYNCING_MAX_NS:
            return 'Syncing...'
        return 'Uncalibrated'
    return 'Initializing...'


def light_color(raw_state: str | None, offset_ns: int | None) -> str:
    """Farbe der Status-LED im Header ableiten."""
    if raw_state in _COLOR_FOR_STATE:
        return _COLOR_FOR_STATE[raw_state]
    if raw_state == 'SLAVE' and offset_ns is not None:
        offset = abs(offset_ns)
        if offset <= LOCKED_MAX_NS:
            return '#4caf50'
        if offset <= SYNCING_MAX_NS:
            return '#ffc107'
        return '#f44336'
    return 'gray'


def tray_state(raw_state: str | None, offset_ns: int | None) -> str:
    """Tray-Icon-Farbe ableiten: 'green', 'yellow' oder 'black'."""
    if raw_state == 'SLAVE' and offset_ns is not None:
        offset = abs(offset_ns)
        if offset <= LOCKED_MAX_NS:
            return 'green'
        if offset <= SYNCING_MAX_NS:
            return 'yellow'
    return 'black'
