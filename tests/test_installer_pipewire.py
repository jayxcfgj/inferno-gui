"""Structural contract tests for install_inferno.sh's PipeWire build routine."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "install_inferno.sh"


def _content() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _section(start_marker: str) -> str:
    """Return the body of a top-level bash function (up to its column-0 closing brace)."""
    return _content().split(start_marker, 1)[1].split("\n}", 1)[0]


def test_run_as_user_helper_contract():
    content = _content()
    assert "run_as_user() {" in content
    body = _section("run_as_user() {")
    assert "TEST_MODE" in body
    assert "sudo -H -u" in body
    assert "XDG_RUNTIME_DIR" in body
    assert 'bash -c "$*"' in body
