"""Read-only PipeWire graph latency estimate.

Shells out to ``sudo -u <user> env K=V ... pw-metadata -n settings`` and
derives an estimate of the round-trip latency caused by the PipeWire
quantum.  With an app forcing the quantum (``clock.force-quantum`` ≠ 0)
the EFFECTIVE quantum is the forced value (``clock.quantum`` still reads
the base value), so the math follows the effective one:

    effective_quantum = force_quantum if force_quantum > 0 else quantum
    per_direction_ms  = (effective_quantum + headroom) / rate * 1000
    round_trip_ms     = 2 * per_direction_ms

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
Every failure path logs a one-line WARNING first: the GUI runs as root
with stderr visible in the user's terminal, so a read that degrades to
"unknown" must say WHY (logging's last-resort handler prints WARNING+
to stderr even without any logging setup).

The session-env helpers come from ``core.pipewire_env`` (stdlib + a
core-only config import) so this module never imports the UI stack:
importing ui.control_tab here created a circular import
(ui/__init__ → main_window → settings_tab → back into this partially
initialized module) that broke helper-first import orders in fresh
interpreters.
"""

import logging
import re
import subprocess

from inferno_gui.core.pipewire_env import (
    get_pipewire_env,
    get_pipewire_env_args,
    get_pipewire_user,
)

_LOG = logging.getLogger(__name__)

# pw-metadata output comes in two shapes depending on the PipeWire
# version: the classic plain form (``clock.quantum = 1024``) and a
# quoted form (``key:'clock.quantum' value:'1024'``) printed by newer
# builds. Both regexes accept either. Decoy keys stay safe because
# every alternation starts with the literal key name (``clock\.quantum``
# never matches ``clock.min-quantum``/``clock.max-quantum``, and
# ``key:'clock\.quantum'`` never matches ``key:'clock.min-quantum'``).
# ``clock.force-quantum`` is a PARSED key (see _FORCE_QUANTUM_RE), not
# a decoy: when an app forces the quantum the effective quantum is the
# forced value, not ``clock.quantum``.
_QUANTUM_RE = re.compile(r"(?:clock\.quantum\s*=\s*|key:'clock\.quantum'\s+value:')(\d+)")
_RATE_RE = re.compile(r"(?:clock\.rate\s*=\s*|key:'clock\.rate'\s+value:')(\d+)")
_FORCE_QUANTUM_RE = re.compile(
    r"(?:clock\.force-quantum\s*=\s*|key:'clock\.force-quantum'\s+value:')(\d+)"
)

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


def _output_tail(proc, limit: int = 200) -> str:
    """Last ~200 chars of stderr+stdout for the nonzero-rc WARNING.

    ``%r`` at the call site keeps embedded newlines escaped, so the log
    stays one line. Non-text (bytes) output from a real run cannot be
    concatenated with the ``\\n`` glue — fall back to repr, and never
    let diagnostics break the never-raise contract.
    """
    try:
        return ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-limit:]
    except TypeError:
        return (repr(proc.stderr) + repr(proc.stdout))[-limit:]


def read_pipewire_latency(headroom_frames: int = 128):
    """Estimate PipeWire graph latency from the current quantum/rate.

    Returns a dict with keys ``quantum`` (int|None, the BASE
    ``clock.quantum``), ``rate`` (int|None), ``headroom`` (int),
    ``force_quantum`` (int|None — None when ``clock.force-quantum`` is
    absent), ``forced`` (bool — True when force-quantum > 0),
    ``per_direction_ms`` (float|None), ``round_trip_ms`` (float|None)
    and ``source`` (str|None), or None when the values are unknown
    (tool missing/nonzero exit/timeout/unparseable output).

    The math uses the EFFECTIVE quantum — with an app forcing the
    quantum (``clock.force-quantum`` ≠ 0, e.g. the Cable app setting
    128) PipeWire runs the forced value while ``clock.quantum`` still
    reads the base value, so::

        effective_quantum = force_quantum if force_quantum > 0 else quantum
        per_direction_ms  = (effective_quantum + headroom) / rate * 1000
    """
    try:
        proc = subprocess.run(
            _pw_metadata_command(),
            env=get_pipewire_env(),
            timeout=_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        _LOG.warning(
            "pw-metadata timed out after %ss",
            getattr(exc, "timeout", _TIMEOUT_S),
        )
        return None
    except UnicodeDecodeError as exc:
        # With text=True the output decode happens INSIDE subprocess.run,
        # so a real decode failure raises here, not in the output handling
        # below. Degrade to "unknown" like every other failure mode.
        _LOG.warning("pw-metadata output undecodable: %s", exc)
        return None
    except OSError as exc:  # FileNotFoundError, PermissionError, ...
        _LOG.warning("pw-metadata failed to run: %s", exc)
        return None

    # A nonzero exit means the tool failed; never trust output from a
    # failed run (it may be partial or unrelated).
    if proc.returncode != 0:
        _LOG.warning(
            "pw-metadata exited rc=%s; tail: %r",
            proc.returncode,
            _output_tail(proc),
        )
        return None

    try:
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        quantum_match = _QUANTUM_RE.search(output)
        rate_match = _RATE_RE.search(output)
        if quantum_match is None or rate_match is None:
            _LOG.warning(
                "pw-metadata output unparseable; head: %r", output[:200]
            )
            return None

        quantum = int(quantum_match.group(1))
        rate = int(rate_match.group(1))
        if rate <= 0:
            _LOG.warning(
                "pw-metadata clock.rate=%s unusable; head: %r",
                rate, output[:200],
            )
            return None

        # clock.force-quantum is optional: absent → None (older
        # PipeWire never prints it); 0 → not forced (PipeWire's own
        # "no force" value).
        force_match = _FORCE_QUANTUM_RE.search(output)
        force_quantum = int(force_match.group(1)) if force_match else None
        forced = force_quantum is not None and force_quantum > 0

        # The effective quantum is the forced value when one is set
        # (real user case: the Cable app forced 128 while
        # clock.quantum still read 1024), otherwise the base value.
        effective_quantum = force_quantum if forced else quantum
        per_direction_ms = (effective_quantum + headroom_frames) * 1000 / rate
    except (TypeError, ValueError) as exc:
        # Non-text output (decode) or non-numeric captures (parse):
        # degrade to "unknown" instead of raising.
        _LOG.warning("pw-metadata output not parseable: %r", exc)
        return None

    return {
        "quantum": quantum,
        "rate": rate,
        "headroom": headroom_frames,
        "force_quantum": force_quantum,
        "forced": forced,
        "per_direction_ms": per_direction_ms,
        "round_trip_ms": 2 * per_direction_ms,
        "source": _SOURCE,
    }
