"""Latency keys in .asoundrc parse/generate: RX_LATENCY_NS / TX_LATENCY_NS.

Inferno itself reads these keys as integer nanoseconds (default 10 ms);
the GUI's job is faithful parse — including malformed values falling back
to the default without raising — and generation in the existing style.
All tests write into pytest tmp dirs, never the real home.
"""
import pytest

from inferno_gui.core.config import InfernoConfig


FIXTURE = """pcm.inferno {
    type inferno

    NAME "TestCard"
    SAMPLE_RATE "48000"

    TX_CHANNELS 24
    RX_CHANNELS 24

    BIND_IP "192.168.1.10"
    RX_LATENCY_NS 5000000
    TX_LATENCY_NS 8000000
}
"""

DEFAULTS = {
    "name": "Inferno",
    "sample_rate": 48000,
    "tx_channels": 24,
    "rx_channels": 24,
    "bind_ip": "",
}


def _write_asoundrc(path, content: str) -> InfernoConfig:
    path.write_text(content)
    # save() uses Path.with_suffix on config_path, so hand it a Path.
    return InfernoConfig(config_path=path)


def test_parse_latency_keys(tmp_path):
    cfg = _write_asoundrc(tmp_path / ".asoundrc", FIXTURE)
    assert cfg.load() is True
    assert cfg.get("rx_latency_ns") == 5_000_000
    assert cfg.get("tx_latency_ns") == 8_000_000


def test_parse_without_latency_keys_uses_defaults(tmp_path):
    base = FIXTURE.replace("    RX_LATENCY_NS 5000000\n", "")
    base = base.replace("    TX_LATENCY_NS 8000000\n", "")
    cfg = _write_asoundrc(tmp_path / ".asoundrc", base)
    assert cfg.load() is True
    assert cfg.get("rx_latency_ns") == 10_000_000
    assert cfg.get("tx_latency_ns") == 10_000_000


@pytest.mark.parametrize("bad", ["abc", "12.5", ""])
def test_malformed_latency_values_fall_back_to_default(tmp_path, bad):
    content = FIXTURE.replace("RX_LATENCY_NS 5000000", f"RX_LATENCY_NS {bad}")
    content = content.replace("TX_LATENCY_NS 8000000", f"TX_LATENCY_NS {bad}")
    cfg = _write_asoundrc(tmp_path / ".asoundrc", content)
    assert cfg.load() is True  # no exception
    assert cfg.get("rx_latency_ns") == 10_000_000
    assert cfg.get("tx_latency_ns") == 10_000_000


def test_save_round_trips_latency_and_keeps_other_keys(tmp_path):
    path = tmp_path / ".asoundrc"
    path.write_text(FIXTURE)
    cfg = InfernoConfig(config_path=path)
    cfg.load()
    cfg.save()

    again = InfernoConfig(config_path=path)
    assert again.load() is True
    assert again.get("rx_latency_ns") == 5_000_000
    assert again.get("tx_latency_ns") == 8_000_000
    assert again.get("name") == "TestCard"
    assert again.get("sample_rate") == 48000
    assert again.get("tx_channels") == 24
    assert again.get("rx_channels") == 24
    assert again.get("bind_ip") == "192.168.1.10"


def test_save_writes_integer_ns_lines(tmp_path):
    path = tmp_path / ".asoundrc"
    path.write_text(FIXTURE)
    cfg = InfernoConfig(config_path=path)
    cfg.load()
    cfg.save()
    content = path.read_text()
    assert "RX_LATENCY_NS 5000000" in content
    assert "TX_LATENCY_NS 8000000" in content
