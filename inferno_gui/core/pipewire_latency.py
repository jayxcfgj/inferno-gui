"""Read-only PipeWire graph latency estimate.

Shells out to ``sudo -u <user> env K=V ... pw-metadata -n settings`` and
derives an estimate of the round-trip latency caused by the PipeWire
quantum:

    per_direction_ms = (quantum + headroom) / rate * 1000
    round_trip_ms    = 2 * per_direction_ms

The headroom covers scheduling/callback overhead that is not part of
the quantum itself (default 128 frames). This module never writes
anything.

The read runs in the INVOKING user's context, not root's: the GUI runs
as root (PTP hardware timestamping needs it), and the pipewire daemon
in the user's runtime session rejects (or lacks the session env for) a
root peer — a plain root ``pw-metadata`` therefore failed in the real
GUI and the estimate silently showed "unknown".  The session env
travels as target-side ``env KEY=value`` command arguments (from
``core.pipewire_env``), where sudo env_reset cannot strip it.

Returns "unknown" (None) whenever the tool is missing, exits nonzero,
times out, or its output cannot be decoded/parsed — never raises.

The session-env helpers come from ``core.pipewire_env`` (stdlib + a
core-only config import) so this module never imports the UI stack:
importing ui.control_tab here created a circular import
(ui/__init__ → main_window → settings_tab → back into this partially
initialized module) that broke helper-first import orders in fresh
interpreters.
"""

import re
import subprocess

from inferno_gui.core.pipewire_env import (
    get_pipewire_env,
    get_pipewire_env_args,
    get_pipewire_user,
)

_QUANTUM_RE = re.compile(r"clock\.quantum\s*=\s*(\d+)")
_RATE_RE = re.compile(r"clock\.rate\s*=\s*(\d+)")

_TIMEOUT_S = 2
_SOURCE = "pw-metadata"


def _pw_metadata_command() -> list[str]:
    """Build the pw-metadata argv, run as the INVOKING user.

    ``sudo -u <user> env K=V ... pw-metadata -n settings``: the session
    env (the same keys get_pipewire_env forces) rides in argv on the
    target side of sudo, where env_reset cannot strip it — a root peer
    is exactly what the user-session daemon rejects.
    """
    user = get_pipewire_user()
    return [
        "sudo", "-u", user, "env",
        *get_pipewire_env_args(user),
        "pw-metadata", "-n", "settings",
    ]


def read_pipewire_latency(headroom_frames: int = 128):
    """Estimate PipeWire graph latency from the current quantum/rate.

    Returns a dict with keys ``quantum`` (int|None), ``rate`` (int|None),
    ``headroom`` (int), ``per_direction_ms`` (float|None),
    ``round_trip_ms`` (float|None) and ``source`` (str|None), or None
    when the values are unknown (tool missing/nonzero exit/timeout/
    unparseable output).
    """
    try:
        proc = subprocess.run(
            _pw_metadata_command(),
            env=get_pipewire_env(),
            timeout=_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return None
    except UnicodeDecodeError:
        # With text=True the output decode happens INSIDE subprocess.run,
        # so a real decode failure raises here, not in the output handling
        # below. Degrade to "unknown" like every other failure mode.
        return None
    except OSError:  # FileNotFoundError, PermissionError, ...
        return None

    # A nonzero exit means the tool failed; never trust output from a
    # failed run (it may be partial or unrelated).
    if proc.returncode != 0:
        return None

    try:
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
    except (TypeError, ValueError):
        # Non-text output (decode) or non-numeric captures (parse):
        # degrade to "unknown" instead of raising.
        return None

    return {
        "quantum": quantum,
        "rate": rate,
        "headroom": headroom_frames,
        "per_direction_ms": per_direction_ms,
        "round_trip_ms": 2 * per_direction_ms,
        "source": _SOURCE,
    }
