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


def test_build_uses_meson_ninja_not_autotools():
    content = _content()
    assert "autogen.sh" not in content
    assert "make -j" not in content
    assert "make install" not in content
    assert "meson setup build --prefix=/usr/local" in content
    assert "ninja -C build" in content
    for bad in (
        "-Dpulse=",
        "-Dsystemd=enabled",
        "-Dffado=",
        "-Dladspa=",
        "-Ddsp=",
        "-Dequalizer=",
        "-Dlibfreeaptx=",
        "-Dliblc3=",
        "-Dlibldac=",
        "-Dlibopenaptx=",
    ):
        assert bad not in content, bad
    for good in (
        "-Dlibpulse=enabled",
        "-Dsystemd-user-service=enabled",
        "-Dbluez5-codec-ldac=enabled",
        "-Dlibffado=disabled",
    ):
        assert good in content, good
    for line in _section("step_pipewire() {").splitlines():
        if "rm -rf" in line:
            assert "run_cmd_sudo" in line, line
    for line in content.splitlines():
        if "ninja -C build install" in line:
            assert "run_cmd_sudo" in line
        if "ldconfig" in line:
            assert "run_cmd_sudo" in line


def test_pipewire_deps_block_is_syntactically_continued():
    lines = _section("step_pipewire() {").splitlines()
    starts = [i for i, ln in enumerate(lines) if "apt-get install -y" in ln]
    assert starts, "deps install command missing"
    block = []
    for ln in lines[starts[0] :]:
        block.append(ln)
        if not ln.rstrip().endswith("\\"):
            break
    assert len(block) >= 5, f"deps list too short: {block}"
    for ln in block[:-1]:
        assert ln.rstrip().endswith("\\"), f"missing line continuation: {ln}"
    assert block[-1].rstrip().endswith('"')
    joined = " ".join(b.rstrip().rstrip("\\") for b in block)
    for pkg in (
        "meson",
        "ninja-build",
        "git",
        "build-essential",
        "libpulse-dev",
        "libjack-jackd2-dev",
        "libglib2.0-dev",
        "libpipewire-0.3-dev",
        "libmysofa-dev",
        "libopenaptx-dev",
        "libldacbt-{abr,enc}-dev",
        "libcamera-dev",
    ):
        assert pkg in joined, pkg


def test_version_check_floor_unchanged():
    # Regression-Guard: laeuft ab sofort gruen, darf nie rot werden
    content = _content()
    assert "1.4.11" in content
    assert '[ "$patch" -ge 11 ]' in content
