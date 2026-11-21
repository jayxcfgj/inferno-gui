"""GUI-side mDNS discovery kick (one-shot PTR probe).

Why this exists
---------------
The netaudio daemon (third party, not modified here) browses
``_netaudio-arc._udp.local`` & friends with the embedded mdns-sd crate.
Its resolve fast-path gives up after ~3 s and recovery rides a slow
re-query ladder - that is why freshly started inferno instances can
take minutes to appear in its UI.  Inferno's responder answers ANY PTR
query for its service types MULTICAST (QU unset), including queries
sent from an ephemeral port, and the daemon's mdns-sd daemon ingests
that same multicast response (service_queriers contains the type) and
re-resolves unresolved instances.  So a single one-shot PTR probe from
this host makes the daemon notice inferno within seconds.  The
netaudio CLI's own ``discovery`` endpoint was removed upstream (404) -
this probe is the clean GUI-side equivalent.

Interface
---------
- ``build_mdns_ptr_query(service_type)``: pure packet builder, no I/O.
- ``send_mdns_ptr_probe(interface_ip, service_type, socket_factory)``:
  sends ONE standard (non-QU) PTR query to 224.0.0.251:5353 via UDP.
  Never raises - a failed probe is logged as a warning, the GUI must
  not crash over it.  ``socket_factory`` is a test seam; ``None`` uses
  ``socket.socket``.
- ``DiscoveryKicker``: ``start(interface_ip)`` arms one single-shot
  QTimer per delay in ``DEFAULT_KICK_DELAYS`` whose timeout sends one
  probe each; ``stop()`` disarms them all.  ``start()`` re-arms (never
  stacks timers); ``stop()`` is idempotent.  ``timers`` exposes the
  armed QTimer objects (read-only copy) and ``interface_ip`` the
  captured interface so callers/tests can inspect the schedule.

Stdlib + PyQt6.QtCore only - no UI imports (keeps the module unit
testable without widgets).
"""

import logging
import socket

from PyQt6.QtCore import QTimer

logger = logging.getLogger(__name__)

# mDNS multicast group and port (RFC 6762).
MDNS_MULTICAST_ADDR = "224.0.0.251"
MDNS_PORT = 5353

# Inferno's Dante service type (without the trailing dot - the qname is
# built from these labels).
DEFAULT_SERVICE_TYPE = "_netaudio-arc._udp.local"

# Kick schedule (seconds after PTP start): early probe for the fast
# path, then a spread-out ladder riding the daemon's slow re-query
# recovery without spamming the multicast group.
DEFAULT_KICK_DELAYS = (1, 6, 15, 35, 65)


def build_mdns_ptr_query(service_type: str = DEFAULT_SERVICE_TYPE) -> bytes:
    """Build a standard DNS/mDNS PTR query packet for ``service_type``.

    Hand-built wire format (no dnspython dependency):

    - header: id 0, flags 0x0000 (standard query, QR=0), qdcount 1,
      an/ns/ar 0
    - question: qname = the service type's labels, split on '.' and
      length-prefixed, terminated by a zero byte; qtype PTR (12);
      qclass IN (1) - the QU top bit (0x8000) stays unset so the
      responder answers multicast, which is exactly what the
      daemon-side mdns-sd querier ingests.

    Pure function, no I/O.  Raises ValueError for empty labels (they
    would silently truncate the queried name).
    """
    qname = b""
    for label in service_type.split("."):
        if not label:
            raise ValueError(
                f"empty DNS label in service type {service_type!r}")
        qname += bytes([len(label)]) + label.encode("ascii")
    qname += b"\x00"

    header = (
        b"\x00\x00"  # ID = 0
        b"\x00\x00"  # flags: standard query (QR=0)
        b"\x00\x01"  # QDCOUNT = 1
        b"\x00\x00"  # ANCOUNT = 0
        b"\x00\x00"  # NSCOUNT = 0
        b"\x00\x00"  # ARCOUNT = 0
    )
    question = qname + b"\x00\x0c" + b"\x00\x01"  # PTR / IN (no QU bit)
    return header + question


def send_mdns_ptr_probe(
    interface_ip: str | None = None,
    service_type: str = DEFAULT_SERVICE_TYPE,
    socket_factory=None,
) -> None:
    """Send one multicast mDNS PTR query for ``service_type``.

    The probe leaves via ``interface_ip`` when given (IP_MULTICAST_IF,
    so it egresses the Dante NIC); otherwise the OS default multicast
    route applies.  ``socket_factory`` (callable taking AF_INET /
    SOCK_DGRAM) is a test seam - ``None`` uses ``socket.socket``.

    NEVER raises: any socket error is logged as a warning and swallowed
    (the GUI must not crash over a failed probe).
    """
    try:
        packet = build_mdns_ptr_query(service_type)
        factory = socket_factory or socket.socket
        sock = factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if interface_ip:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                socket.inet_aton(interface_ip))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            sock.sendto(packet, (MDNS_MULTICAST_ADDR, MDNS_PORT))
        finally:
            sock.close()
    except Exception as exc:  # noqa: BLE001 - probe failures are fatal-free
        logger.warning("mDNS discovery probe failed: %s", exc)


class DiscoveryKicker:
    """Arms one-shot mDNS PTR probes on a delay schedule.

    Usage (see ui/control_tab.py for the wiring): on PTP start call
    ``start(interface_ip)`` with the CURRENT interface address so the
    probes leave via the Dante NIC; on PTP stop call ``stop()``.
    Each armed QTimer is single-shot; its timeout sends exactly one
    probe.  ``start()`` while armed re-arms cleanly (no stacked timers);
    ``stop()`` is idempotent and also safe before any ``start()``.
    """

    def __init__(self, parent=None, delays=DEFAULT_KICK_DELAYS,
                 service_type: str = DEFAULT_SERVICE_TYPE,
                 socket_factory=None):
        self._parent = parent
        self._delays = tuple(delays)
        self._service_type = service_type
        self._socket_factory = socket_factory
        self._interface_ip: str | None = None
        self._timers: list[QTimer] = []

    @property
    def timers(self) -> list[QTimer]:
        """The currently armed single-shot QTimers (read-only copy)."""
        return list(self._timers)

    @property
    def interface_ip(self) -> str | None:
        """The interface IP captured by the last ``start()`` call."""
        return self._interface_ip

    def start(self, interface_ip: str | None = None) -> None:
        """(Re-)arm the kick schedule; probes go out via interface_ip."""
        self.stop()
        self._interface_ip = interface_ip
        for delay in self._delays:
            timer = QTimer(self._parent)
            timer.setSingleShot(True)
            timer.timeout.connect(self._send_probe)
            timer.start(delay * 1000)
            self._timers.append(timer)

    def stop(self) -> None:
        """Disarm all scheduled probes (idempotent)."""
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers = []

    def _send_probe(self) -> None:
        send_mdns_ptr_probe(
            self._interface_ip,
            service_type=self._service_type,
            socket_factory=self._socket_factory,
        )
