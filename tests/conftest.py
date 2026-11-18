"""Test-wide setup: keep the suite from touching real user settings.

user_settings() resolves to <actual_user_home>/.config/InfernoGUI/*.conf.
Redirect that home to a temp dir so no test reads or writes the
developer's real settings. (The QSettings NativeFormat redirect in
test_layout_smoke no longer covers the app once it uses explicit INI
paths via user_settings.)
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import inferno_gui.core.app_settings as _app_settings
except ImportError:  # app_settings does not exist yet (TDD red phase)
    _app_settings = None

if _app_settings is not None:
    _TEMP_HOME = Path(tempfile.mkdtemp(prefix="inferno-gui-test-home-"))
    _app_settings.get_actual_user_home = lambda: _TEMP_HOME
