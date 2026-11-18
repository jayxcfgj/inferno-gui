"""Open URLs and local files in the invoking user's desktop session.

The GUI runs as root (PTP hardware timestamping requires it), so
QDesktopServices.openUrl launches the browser in root's environment —
HOME=/root, no session bus — and the boolean result is discarded, so
nothing opens.  The pattern that already works for the NetAudio
launcher in control_tab is delegating to ``sudo -u <user> xdg-open``,
forwarding the user's session environment (run_gui.sh exports it
before sudo'ing the GUI, so reading ``os.environ`` is correct).
"""

import logging
import os
import pwd

from PyQt6.QtCore import QProcess, QProcessEnvironment

from inferno_gui.core.config import get_actual_user_home

_LOG = logging.getLogger(__name__)

# Session variables the child needs to reach the user's desktop (the
# same set run_gui.sh / control_tab._get_pipewire_env forward).  Only
# variables that are actually set in our environment are forwarded.
_SESSION_ENV_KEYS = (
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
)


def _session_env() -> dict:
    """Current environment filtered to the session variables (set ones only)."""
    return {key: os.environ[key] for key in _SESSION_ENV_KEYS if key in os.environ}


def _target_user() -> str:
    """The user on whose desktop the URL should open.

    ``SUDO_USER`` when running under sudo, otherwise the owner of the
    actual user's home directory.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        return sudo_user
    try:
        return pwd.getpwuid(get_actual_user_home().stat().st_uid).pw_name
    except (KeyError, OSError):
        pass
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return "root"


def open_url_as_user(url: str) -> None:
    """Open ``url`` (a link or a local file path) as the invoking user.

    Launches ``sudo -u <user> xdg-open <url>`` as a detached process
    with the user's session environment forwarded.  Never raises — a
    failed launch is logged as a warning naming the URL (a menu action
    must not take the GUI down).
    """
    user = _target_user()

    proc = QProcess()
    proc.setProgram("sudo")
    proc.setArguments(["-u", user, "xdg-open", url])
    env = QProcessEnvironment()
    for key, value in _session_env().items():
        env.insert(key, value)
    proc.setProcessEnvironment(env)

    try:
        result = proc.startDetached()
        # PyQt6 returns a (success, pid) tuple; stubs may return a bool.
        ok = result[0] if isinstance(result, tuple) else bool(result)
    except Exception as exc:
        _LOG.warning("Failed to start xdg-open for %s (%s)", url, exc)
        return
    if not ok:
        _LOG.warning("xdg-open did not start for URL %s (user %s)", url, user)
