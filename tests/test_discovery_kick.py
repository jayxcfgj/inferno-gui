# tests/test_discovery_kick.py
"""Unit tests: GUI-side mDNS discovery kick (core/discovery_kick.py).

The netaudio daemon's embedded mdns-sd resolve fast-path gives up after
~3 s and recovery rides a slow re-query ladder, so freshly started
inferno instances can take minutes to appear in its UI. Inferno's
responder answers ANY PTR query for its service types MULTICAST, and
the daemon's mdns-sd daemon ingests that same multicast response and
re-resolves unresolved instances - so a one-shot PTR probe from this
host makes the daemon notice inferno within seconds.

Under test:
- build_mdns_ptr_query(): pure packet builder (no I/O).
- send_mdns_ptr_probe(): ONE query to the mDNS multicast group; must
  NEVER raise (the GUI must not crash over a failed probe).
- DiscoveryKicker: one-shot QTimers armed by start(interface_ip),
  cleared by stop(); repeated start must not stack timers.

Run: QT_QPA_PLATFORM=offscreen uv run --no-project --with pytest \
    --with PyQt6 python -m pytest tests/test_discovery_kick.py -q
"""
import logging
import os
import socket
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from inferno_gui.core.discovery_kick import (
    DEFAULT_KICK_DELAYS,
    DiscoveryKicker,
    build_mdns_ptr_query,
    send_mdns_ptr_probe,
)

# ── build_mdns_ptr_query: pure packet builder ─────────────────────────


def test_default_query_is_exact_bytes():
    """Wire format: 12-byte header (id 0, standard query QR=0, qdcount 1),
    qname labels length-prefixed with a terminal zero byte, QTYPE PTR,
    QCLASS IN - the QU top bit stays unset so the answer goes multicast."""
    expected = (
        b"\x00\x00"                # ID = 0
        b"\x00\x00"                # flags = 0x0000 (standard query, QR=0)
        b"\x00\x01"                # QDCOUNT = 1
        b"\x00\x00"                # ANCOUNT = 0
        b"\x00\x00"                # NSCOUNT = 0
        b"\x00\x00"                # ARCOUNT = 0
        b"\x0d_netaudio-arc"       # label, length prefix 13
        b"\x04_udp"
        b"\x05local"
        b"\x00"                    # qname root terminator
        b"\x00\x0c"                # QTYPE = PTR (12)
        b"\x00\x01"                # QCLASS = IN (1), QU bit unset
    )
    assert build_mdns_ptr_query() == expected


def test_custom_service_type_encodes_its_labels():
    got = build_mdns_ptr_query("_http._tcp.local")
    assert got == (
        b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        b"\x05_http\x04_tcp\x05local\x00"
        b"\x00\x0c\x00\x01"
    )


def test_empty_label_is_rejected():
    # An empty label would terminate the qname early and silently query
    # a different name - fail loudly instead.
    with pytest.raises(ValueError):
        build_mdns_ptr_query("_netaudio-arc..local")


# ── send_mdns_ptr_probe: one multicast packet, never raises ───────────


class FakeSocket:
    """Records setsockopt/sendto/close; no real I/O ever happens."""

    def __init__(self, family, sock_type):
        assert family == socket.AF_INET, "probe must use IPv4"
        assert sock_type == socket.SOCK_DGRAM, "probe must use UDP"
        self.setsockopt_calls = []
        self.sent = []
        self.closed = False

    def setsockopt(self, level, optname, value):
        self.setsockopt_calls.append((level, optname, value))

    def sendto(self, data, addr):
        self.sent.append((bytes(data), addr))

    def close(self):
        self.closed = True


class FakeSocketFactory:
    """Injectable socket factory: hands out FakeSockets."""

    def __init__(self):
        self.sockets = []

    def __call__(self, family, sock_type):
        sock = FakeSocket(family, sock_type)
        self.sockets.append(sock)
        return sock


def test_probe_goes_to_mdns_multicast_group():
    factory = FakeSocketFactory()
    send_mdns_ptr_probe(socket_factory=factory)
    assert len(factory.sockets) == 1, "one probe = one socket"
    sock = factory.sockets[0]
    assert len(sock.sent) == 1
    packet, addr = sock.sent[0]
    assert addr == ("224.0.0.251", 5353)
    assert packet == build_mdns_ptr_query()
    # Multicast TTL 255 so delivery across local-network hops is safe.
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255) \
        in sock.setsockopt_calls
    # No interface pinned: IP_MULTICAST_IF must not be set.
    assert all(opt != socket.IP_MULTICAST_IF
               for (_lvl, opt, _v) in sock.setsockopt_calls)
    assert sock.closed, "socket must be closed after the probe"


def test_probe_with_interface_ip_pins_multicast_if():
    factory = FakeSocketFactory()
    send_mdns_ptr_probe("192.168.7.42", socket_factory=factory)
    sock = factory.sockets[0]
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
            socket.inet_aton("192.168.7.42")) in sock.setsockopt_calls


def test_probe_survives_sendto_error(caplog):
    class _BrokenSocket:
        def setsockopt(self, *args):
            pass

        def sendto(self, *args):
            raise OSError("network unreachable")

        def close(self):
            pass

    with caplog.at_level(logging.WARNING,
                         logger="inferno_gui.core.discovery_kick"):
        # Must not raise - a failed probe may never crash the GUI.
        send_mdns_ptr_probe("10.0.0.9",
                            socket_factory=lambda f, t: _BrokenSocket())
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "socket error must be logged as a warning"
    assert any("probe" in r.getMessage() for r in warnings)


def test_probe_survives_socket_creation_error(caplog):
    def broken_factory(family, sock_type):
        raise OSError("cannot create socket")

    with caplog.at_level(logging.WARNING,
                         logger="inferno_gui.core.discovery_kick"):
        send_mdns_ptr_probe(None, socket_factory=broken_factory)  # no raise
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ── DiscoveryKicker: one-shot timers after PTP start ──────────────────

_APP = None


def _get_app():
    """QApplication reference held module-globally (PyQt destroys the C++
    app when the last Python wrapper is garbage-collected)."""
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def test_kicker_start_arms_single_shot_timers():
    _get_app()
    kicker = DiscoveryKicker()
    kicker.start("192.0.2.10")
    timers = kicker.timers
    assert DEFAULT_KICK_DELAYS == (1, 6, 15, 35, 65), \
        "default kick schedule changed"
    assert [t.interval() for t in timers] \
        == [d * 1000 for d in DEFAULT_KICK_DELAYS]
    assert all(t.isSingleShot() for t in timers)
    assert all(t.isActive() for t in timers)
    assert kicker.interface_ip == "192.0.2.10"


def test_kicker_repeated_start_does_not_stack_timers():
    _get_app()
    kicker = DiscoveryKicker()
    kicker.start("192.0.2.10")
    old_timers = kicker.timers
    kicker.start("192.0.2.11")
    assert len(kicker.timers) == len(DEFAULT_KICK_DELAYS)
    assert all(not t.isActive() for t in old_timers), \
        "timers from a previous start must be stopped"
    assert kicker.interface_ip == "192.0.2.11"


def test_kicker_stop_clears_timers_and_is_idempotent():
    _get_app()
    kicker = DiscoveryKicker()
    kicker.stop()  # stop before any start: no-op
    assert kicker.timers == []
    kicker.start("192.0.2.10")
    assert kicker.timers
    kicker.stop()
    assert kicker.timers == []
    kicker.stop()  # second stop: still fine
    assert kicker.timers == []


def test_kicker_timer_timeouts_each_send_one_probe():
    _get_app()
    factory = FakeSocketFactory()
    kicker = DiscoveryKicker(socket_factory=factory)
    kicker.start("192.0.2.10")
    for timer in kicker.timers:
        timer.timeout.emit()  # fire the signal without wall-clock waiting
    assert len(factory.sockets) == len(DEFAULT_KICK_DELAYS)
    for sock in factory.sockets:
        assert len(sock.sent) == 1, "each timeout sends exactly one probe"
        _packet, addr = sock.sent[0]
        assert addr == ("224.0.0.251", 5353)
        assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                socket.inet_aton("192.0.2.10")) in sock.setsockopt_calls
        assert sock.closed
