"""Inferno GUI Core Package."""

from .version import (
    __version__,
    __app_name__,
    __description__,
    __license__,
    __author__,
    __inferno_author__,
)
from .config import (
    InfernoConfig,
    StatimeConfig,
    InfernoConfigError,
    get_available_interfaces,
    get_interface_ip,
    get_work_dir,
    get_statime_dir,
    get_inferno_dir,
    get_default_statime_config,
    get_statime_binary,
    get_inferno_plugin,
)
from .log_parser import (
    StatimeLogParser,
    ParsedLogEntry,
    LogSeverity,
    format_log_entry,
)

__all__ = [
    # Version
    '__version__',
    '__app_name__',
    '__description__',
    '__license__',
    '__author__',
    '__inferno_author__',
    # Config
    'InfernoConfig',
    'StatimeConfig',
    'InfernoConfigError',
    'get_available_interfaces',
    'get_interface_ip',
    'get_work_dir',
    'get_statime_dir',
    'get_inferno_dir',
    'get_default_statime_config',
    'get_statime_binary',
    'get_inferno_plugin',
    # Log parser
    'StatimeLogParser',
    'ParsedLogEntry',
    'LogSeverity',
    'format_log_entry',
]