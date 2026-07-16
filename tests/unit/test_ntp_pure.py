"""Pure tests for the NTP offset math — no network. Loads ntp.py by path (stdlib-only module)."""
from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

_CC = Path(__file__).resolve().parents[2] / "custom_components" / "gridwitness"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"gw_{name}", _CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ntp = _load("ntp")


def _encode(unix_seconds: float) -> tuple[int, int]:
    hi = int(unix_seconds) + ntp._NTP_UNIX_DELTA
    lo = int((unix_seconds - int(unix_seconds)) * 2 ** 32)
    return hi, lo


def _packet(t2: float, t3: float) -> bytes:
    rx_hi, rx_lo = _encode(t2)
    tx_hi, tx_lo = _encode(t3)
    return b"\x00" * 32 + struct.pack("!IIII", rx_hi, rx_lo, tx_hi, tx_lo)


def test_parse_offset_recovers_known_offset():
    # local t1=1000.0, t4=1000.2; server t2=1005.1, t3=1005.1 -> offset 5.0s, delay 0.2s
    data = _packet(1005.1, 1005.1)
    offset, delay = ntp.parse_offset(data, t1=1000.0, t4=1000.2)
    assert abs(offset - 5.0) < 1e-3
    assert abs(delay - 0.2) < 1e-3


def test_parse_offset_zero_when_synced():
    data = _packet(1000.05, 1000.05)
    offset, _ = ntp.parse_offset(data, t1=1000.0, t4=1000.1)
    assert abs(offset) < 1e-3


def test_short_response_rejected():
    try:
        ntp.parse_offset(b"\x00" * 10, 0.0, 0.1)
    except ValueError:
        return
    raise AssertionError("expected ValueError on short response")


def test_authoritative_median_ignores_outlier(monkeypatch):
    # three servers report 5.0, 5.1, 100.0 -> median 5.1 (outlier ignored)
    calls = iter([5.0, 5.1, 100.0])
    monkeypatch.setattr(ntp, "query_one", lambda *a, **k: next(calls))
    got = ntp.authoritative_offset(("a", "b", "c"), min_responses=2)
    assert abs(got - 5.1) < 1e-9


def test_authoritative_none_when_too_few(monkeypatch):
    monkeypatch.setattr(ntp, "query_one", lambda *a, **k: None)
    assert ntp.authoritative_offset(("a", "b"), min_responses=2) is None
