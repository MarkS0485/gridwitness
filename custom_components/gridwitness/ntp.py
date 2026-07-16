"""Authoritative node clock offset via multiple NTP servers.

The host clock Home Assistant runs on can drift; since we stamp samples with it, drift biases every
timestamp. This module asks several public NTP servers for true UTC and returns the median offset
(robust to one bad/asymmetric server). The coordinator refreshes it every few hours and applies it
when stamping ``ha_receive`` samples — a better local truth than the server round-trip alone, and
independent of it.

Offset convention: ``offset = true_utc - local_clock`` (seconds). Corrected time = local + offset.

The parsing/statistics helpers are pure and unit-tested; the socket call is sync and meant to run in
Home Assistant's executor.
"""
from __future__ import annotations

import socket
import struct
from statistics import median

# NTP timestamp epoch (1900-01-01) to Unix epoch (1970-01-01) in seconds.
_NTP_UNIX_DELTA = 2208988800

# LI=0, VN=4 (SNTPv4), Mode=3 (client) -> 0b00_100_011 = 0x23 in the first byte.
_REQUEST = b"\x23" + 47 * b"\x00"

DEFAULT_SERVERS: tuple[str, ...] = (
    "time.cloudflare.com",
    "time.google.com",
    "pool.ntp.org",
    "uk.pool.ntp.org",
)

# Reject a sample whose round-trip delay exceeds this — asymmetric/slow paths give poor offsets.
_MAX_DELAY_S = 1.0


def _to_seconds(hi: int, lo: int) -> float:
    """NTP 64-bit fixed-point (seconds.fraction) since 1900 -> Unix seconds (float)."""
    return (hi - _NTP_UNIX_DELTA) + (lo / 2 ** 32)


def parse_offset(data: bytes, t1: float, t4: float) -> tuple[float, float]:
    """Return (offset, delay) in seconds from a 48-byte NTP reply and the client send/recv times.

    t1 = client transmit (local), t4 = client receive (local); t2/t3 come from the packet.
    """
    if len(data) < 48:
        raise ValueError("short NTP response")
    # receive timestamp @ bytes 32-39, transmit timestamp @ bytes 40-47
    rx_hi, rx_lo, tx_hi, tx_lo = struct.unpack("!IIII", data[32:48])[0:4]
    t2 = _to_seconds(rx_hi, rx_lo)
    t3 = _to_seconds(tx_hi, tx_lo)
    offset = ((t2 - t1) + (t3 - t4)) / 2.0
    delay = (t4 - t1) - (t3 - t2)
    return offset, delay


def query_one(server: str, *, timeout: float, now) -> float | None:
    """Query a single NTP server. Returns offset in seconds, or None on failure/poor delay.

    ``now`` is a zero-arg callable returning current Unix seconds (injected for testability).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        t1 = now()
        sock.sendto(_REQUEST, (server, 123))
        data, _ = sock.recvfrom(48)
        t4 = now()
        offset, delay = parse_offset(data, t1, t4)
        if delay > _MAX_DELAY_S or delay < 0:
            return None
        return offset
    except (OSError, ValueError):
        return None
    finally:
        sock.close()


def authoritative_offset(
    servers: tuple[str, ...] = DEFAULT_SERVERS,
    *,
    timeout: float = 3.0,
    min_responses: int = 2,
    now=None,
) -> float | None:
    """Median NTP offset (seconds) across servers, or None if fewer than ``min_responses`` reply.

    Blocking — run in an executor. Median makes it robust to a single bad server.
    """
    import time as _time

    now = now or _time.time
    offsets = [o for s in servers if (o := query_one(s, timeout=timeout, now=now)) is not None]
    if len(offsets) < min_responses:
        return None
    return median(offsets)
