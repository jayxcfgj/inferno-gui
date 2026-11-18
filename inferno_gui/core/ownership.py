"""Give files written by a root-launched GUI back to the invoking user.

The GUI must run under sudo for PTP hardware timestamping, so every file
it writes (~/.asoundrc, the statime TOMLs, the QSettings files under
.config/InfernoGUI) would end up owned by root — and the invoking user
could no longer edit them in a normal, non-sudo run.  Both config
save() paths and every QSettings write therefore hand their files back
to the user sudo launched the process for.
"""
import logging
import os
import pwd
from pathlib import Path
from typing import Optional, Tuple, Union

from inferno_gui.core.config import get_actual_user_home

logger = logging.getLogger(__name__)


def _target_uid_gid() -> Optional[Tuple[int, int]]:
    """Resolve the (uid, gid) written files should belong to.

    Prefers $SUDO_USER (set when running under sudo); falls back to the
    owner of the actual user's home directory.  Returns None when no
    owner can be resolved.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            entry = pwd.getpwnam(sudo_user)
            return entry.pw_uid, entry.pw_gid
        except KeyError:
            logger.warning(
                "SUDO_USER %r has no passwd entry, falling back to home owner",
                sudo_user,
            )
    try:
        home = get_actual_user_home()
        stat = os.stat(home)
        return stat.st_uid, stat.st_gid
    except Exception as exc:  # never let ownership bookkeeping break a save
        logger.warning("Cannot resolve invoking user from home directory: %s", exc)
        return None


def chown_to_invoking_user(path: Union[str, Path]) -> None:
    """Give a file written as root back to the invoking user.

    No-op when not running as root, when no invoking user can be
    resolved, or when the file already belongs to them.  Never raises:
    failures are logged and ignored.
    """
    if os.getuid() != 0:
        return
    target = _target_uid_gid()
    if target is None:
        return
    uid, gid = target
    path = os.fspath(path)
    try:
        stat = os.stat(path)
    except OSError:
        return  # Nothing was written; nothing to hand back.
    if stat.st_uid == uid and stat.st_gid == gid:
        return  # Already owned by the invoking user.
    try:
        os.chown(path, uid, gid)
        logger.info("chown %s -> uid=%d gid=%d", path, uid, gid)
    except OSError as exc:
        logger.warning("chown failed for %s: %s", path, exc)


def chown_qsettings(settings) -> None:
    """Flush a QSettings object and hand its file to the invoking user.

    Args:
        settings: a QSettings instance; sync() flushes pending writes and
            fileName() names the INI file to chown.
    """
    settings.sync()
    chown_to_invoking_user(settings.fileName())
