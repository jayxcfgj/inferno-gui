"""Application settings stored in the invoking user's home directory.

When the GUI runs under sudo (required for PTP hardware timestamping),
QSettings' default NativeFormat location resolves to /root/.config, so
the user's saved interface, PTP version and window geometry silently
land in root's home and are never seen again by a non-sudo run.  All
application settings therefore go through user_settings(), which places
them under the *actual* user's home:

    <actual_user_home>/.config/InfernoGUI/<scope>.conf

Note: settings migration from /root/.config is intentionally skipped
(user-approved reset).
"""
from PyQt6.QtCore import QSettings

from inferno_gui.core.config import get_actual_user_home


def user_settings(scope: str) -> QSettings:
    """Return INI-format QSettings for the given scope in the user's home.

    Args:
        scope: settings file name, e.g. "control" or "window".

    The directory is created on demand; the file itself is only written
    when a value is actually stored.
    """
    base = get_actual_user_home() / ".config" / "InfernoGUI"
    base.mkdir(parents=True, exist_ok=True)
    return QSettings(str(base / f"{scope}.conf"), QSettings.Format.IniFormat)
