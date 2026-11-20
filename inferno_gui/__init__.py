"""Inferno GUI - A Linux desktop tool for managing Inferno Dante/AES67 virtual soundcard."""

import os

# The GUI runs as root but is installed in the invoking user's tree. Root-
# written bytecode caches become root-owned and stale-cache edits invisible
# to the user. Never write .pyc at all.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from .core.version import (
    __version__,
    __app_name__,
    __description__,
    __license__,
    __author__,
    __inferno_author__,
)

__all__ = [
    '__version__',
    '__app_name__',
    '__description__',
    '__license__',
    '__author__',
    '__inferno_author__',
]