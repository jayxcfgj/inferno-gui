"""Open URLs and local files in the invoking user's desktop session.

The GUI runs as root (PTP hardware timestamping requires it), so
QDesktopServices.openUrl launches the browser in root's environment —
HOME=/root, no session bus — and the boolean result is discarded, so
nothing opens.  The pattern that already works for the NetAudio
launcher in control_tab is delegating to ``sudo -u <user> ...`` — but
the session environment cannot ride on sudo's own environment: sudo
env_reset strips it before the target command runs.  It therefore
travels as target-side ``env KEY=value`` command arguments, with
UID-derived defaults for keys the current environment lacks (a direct
``sudo inferno-gui`` launch bypasses run_gui.sh's env reconstruction,
so XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS may be missing entirely).
"""

import logging
import os
import pwd
from typing import List, Optional

from PyQt6.QtCore import QProcess

from inferno_gui.core.config import get_actual_user_home

_LOG = logging.getLogger(__name__)

# Session variables the child needs to reach the user's desktop (the
# same set run_gui.sh / control_tab._get_pipewire_env forward).  Only
# variables that are actually set in our environment are forwarded;
# XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS additionally have
# UID-derived defaults for when the environment lacks them.
_SESSION_ENV_KEYS = (
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
)


def _target_uid(user: str) -> Optional[int]:
    """UID of the target user, or None when it cannot be resolved."""
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError:
        return None


def _target_env_args(user: str) -> List[str]:
    """Session env for the target user, as ``env KEY=value`` arguments.

    Values come from the current environment when set (run_gui.sh
    exports them before sudo'ing the GUI); otherwise
    XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS fall back to the
    target user's UID-derived paths so xdg-open still finds the
    runtime directory and the session bus.
    """
    uid = _target_uid(user)
    defaults = {}
    if uid is not None:
        defaults["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
        defaults["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    args = []
    for key in _SESSION_ENV_KEYS:
        if key in os.environ:
            args.append(f"{key}={os.environ[key]}")
        elif key in defaults:
            args.append(f"{key}={defaults[key]}")
    return args


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

    Launches ``sudo -u <user> env K=V ... xdg-open <url>`` as a
    detached process.  The session environment travels as env command
    arguments on the target side, where sudo env_reset cannot strip
    it; keys missing from the current environment get UID-derived
    defaults.  Never raises — a failed launch is logged as a warning
    naming the URL (a menu action must not take the GUI down).
    """
    user = _target_user()
    env_args = _target_env_args(user)

    proc = QProcess()
    proc.setProgram("sudo")
    proc.setArguments(["-u", user, "env", *env_args, "xdg-open", url])

    try:
        result = proc.startDetached()
        # PyQt6 returns a (success, pid) tuple; stubs may return a bool.
        ok = result[0] if isinstance(result, tuple) else bool(result)
    except Exception as exc:
        _LOG.warning("Failed to start xdg-open for %s (%s)", url, exc)
        return
    if not ok:
        _LOG.warning("xdg-open did not start for URL %s (user %s)", url, user)
