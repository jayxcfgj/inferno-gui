"""Read-only PipeWire graph latency estimate.

Shells out to ``pw-metadata -n settings`` and derives an estimate of the
round-trip latency caused by the PipeWire quantum:

    per_direction_ms = (quantum + headroom) / rate * 1000
    round_trip_ms    = 2 * per_direction_ms

The headroom covers scheduling/callback overhead that is not part of the
quantum itself (default 128 frames). This module never writes anything.

Returns "unknown" (None) whenever the tool is missing, times out, or its
output cannot be parsed — never raises.
"""

import re
import subprocess

# _get_pipewire_env forces XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS to
# the invoking user's session so PipeWire commands reach the user's
# pipewire instance (the GUI may run under sudo for PTP timestamping).
# Importing it (instead of copying the logic) keeps a single source of
# truth; control_tab does not import this module, so there is no cycle.
# The import pulls in PyQt6 transitively (ui/__init__ -> main_window),
# which is always available in this application.
from inferno_gui.ui.control_tab import _get_pipewire_env

_QUANTUM_RE = re.compile(r"clock\.quantum\s*=\s*(\d+)")
_RATE_RE = re.compile(r"clock\.rate\s*=\s*(\d+)")

_TIMEOUT_S = 2
_SOURCE = "pw-metadata"


def read_pipewire_latency(headroom_frames: int = 128):
    """Estimate PipeWire graph latency from the current quantum/rate.

    Returns a dict with keys ``quantum`` (int|None), ``rate`` (int|None),
    ``headroom`` (int), ``per_direction_ms`` (float|None),
    ``round_trip_ms`` (float|None) and ``source`` (str|None), or None
    when the values are unknown (tool missing/timeout/unparseable).
    """
    try:
        proc = subprocess.run(
            ["pw-metadata", "-n", "settings"],
            env=_get_pipewire_env(),
            timeout=_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError:  # FileNotFoundError, PermissionError, ...
        return None

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    quantum_match = _QUANTUM_RE.search(output)
    rate_match = _RATE_RE.search(output)
    if quantum_match is None or rate_match is None:
        return None

    quantum = int(quantum_match.group(1))
    rate = int(rate_match.group(1))
    if rate <= 0:
        return None

    per_direction_ms = (quantum + headroom_frames) * 1000 / rate
    return {
        "quantum": quantum,
        "rate": rate,
        "headroom": headroom_frames,
        "per_direction_ms": per_direction_ms,
        "round_trip_ms": 2 * per_direction_ms,
        "source": _SOURCE,
    }
