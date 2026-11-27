# tests/test_version_bump.py
"""Release v1.0.1: the version lives in ONE place — core/version.py.

main.py used to hardcode "1.0.0" in setApplicationVersion; the about
dialog already imports __version__. The bump to 1.0.1 (BIND_IP sync +
standalone installer download) must not leave stray hardcoded copies
behind.

Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_version_bump.py -q
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_1_0_1():
    from inferno_gui.core.version import __version__
    assert __version__ == "1.0.1"


def test_pyproject_version_matches():
    """The distribution metadata (pyproject.toml) ships the same
    version as the package."""
    content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.0.1"' in content


def test_no_hardcoded_version_strings_in_package():
    """core/version.py is the single source of truth: no other module
    in the package hardcodes a version literal (catches the old
    app.setApplicationVersion("1.0.0") copy)."""
    pkg = ROOT / "inferno_gui"
    offenders = []
    for py in sorted(pkg.rglob("*.py")):
        if py.name == "version.py":
            continue
        text = py.read_text(encoding="utf-8")
        for needle in ('"1.0.0"', '"1.0.1"'):
            if needle in text:
                offenders.append(f"{py.relative_to(ROOT)}: {needle}")
    assert offenders == []
