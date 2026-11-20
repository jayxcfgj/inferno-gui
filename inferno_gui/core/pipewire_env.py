"""User-session environment for PipeWire commands.

The GUI runs as root (sudo, for PTP hardware timestamping), so PipeWire
commands must target the *invoking* user's session, not root's: this
module forces XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS to the invoking
user's runtime directory and session bus, and resolves the invoking
user for `sudo -u <user>` delegation.

Core-only by design (os, pwd + core.config): ``core.pipewire_latency``
imports it directly, and importing a core module must never pull in
the UI stack (``inferno_gui.ui.control_tab`` would drag in ui/__init__
→ main_window → settings_tab and back — a circular import that breaks
helper-first import orders). The UI (control_tab) and the core helper
share this single source of truth.

The returned dict works for ``subprocess.run(..., env=...)`` and can be
converted for QProcess via
``QProcessEnvironment.fromSystemEnvironment().set(get_pipewire_env())``.
For commands launched through ``sudo -u <user>`` (where sudo env_reset
strips the environment before the target command runs),
``get_pipewire_env_args()`` returns the same session keys as
target-side ``env KEY=value`` command arguments instead.
"""

import os
import pwd

from inferno_gui.core.config import get_actual_user_home


def get_pipewire_env() -> dict:
    """Return the environment dict for PipeWire commands to connect to
    the actual user's session.

    When running under sudo (required for PTP hardware timestamping),
    PipeWire commands must target the actual user's PipeWire instance,
    not root's.
    """
    # First try to get the actual user from SUDO_USER
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user and sudo_user != 'root':
        try:
            uid = pwd.getpwnam(sudo_user).pw_uid
        except KeyError:
            uid = os.getuid()
    else:
        # No SUDO_USER - try to detect from existing XDG_RUNTIME_DIR
        runtime = os.environ.get('XDG_RUNTIME_DIR', '')
        if runtime and '/run/user/' in runtime:
            # Extract UID from existing runtime dir
            # (e.g., /run/user/1000 -> 1000)
            try:
                uid = int(runtime.split('/')[-2])
            except (ValueError, IndexError):
                uid = os.getuid()
        else:
            uid = os.getuid()

    env = os.environ.copy()
    env['XDG_RUNTIME_DIR'] = f'/run/user/{uid}'
    env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'
    return env


def get_pipewire_user() -> str:
    """The invoking user on whose behalf PipeWire commands run.

    Same resolution as ``ui.url_utils._target_user``: ``SUDO_USER``
    when running under sudo, otherwise the owner of the actual user's
    home directory.  Replicated here rather than imported: importing
    ``ui.url_utils`` would pull in PyQt6 and the whole UI stack
    (``inferno_gui.ui.__init__`` → main_window → settings_tab → back),
    which this core module must never do — see the module docstring.
    Never raises: unresolvable states degrade to the current user.
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


def get_pipewire_env_args(user: str | None = None) -> list[str]:
    """Session env for ``sudo -u <user>`` launches, as ``env KEY=value``
    command arguments.

    The same two keys ``get_pipewire_env`` forces —
    XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS — with the target
    user's UID-derived values, riding on the TARGET side of sudo where
    env_reset cannot strip them.
    """
    if user is None:
        user = get_pipewire_user()
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return []
    return [
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
    ]
