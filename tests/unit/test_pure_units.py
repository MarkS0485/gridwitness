"""Pure-Python unit tests that don't need the Home Assistant test harness.

They load the modules by file path so importing the package __init__ (which pulls homeassistant) is
avoided. Covers the earn-the-ask channel model (const.py) and the offline buffer (buffer.py).
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CC = Path(__file__).resolve().parents[2] / "custom_components" / "gridwitness"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"gw_{name}", _CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


const = _load("const")
buffer = _load("buffer")


# --- const.py: channel model integrity ------------------------------------------------------------

def test_all_channels_partition_cleanly():
    assert const.ELECTRICAL_CHANNELS.isdisjoint(const.WEATHER_CHANNELS)


def test_device_class_map_targets_known_channels():
    known = const.ELECTRICAL_CHANNELS | const.WEATHER_CHANNELS
    assert set(const.DEVICE_CLASS_CHANNELS.values()) <= known


def test_consent_groups_reference_known_channels():
    known = const.ELECTRICAL_CHANNELS | const.WEATHER_CHANNELS
    for grp, spec in const.CONSENT_GROUPS.items():
        assert set(spec["channels"]) <= known, grp


def test_high_sensitivity_channels_are_the_load_channels():
    assert const.HIGH_SENSITIVITY_CHANNELS == {"current_a", "power_w", "power_factor"}
    # and they live in the current_power group, never bundled with frequency/voltage
    assert set(const.CONSENT_GROUPS["current_power"]["channels"]) == const.HIGH_SENSITIVITY_CHANNELS


def test_default_on_is_frequency_only():
    on_by_default = {g for g, s in const.CONSENT_GROUPS.items() if s["default"]}
    assert on_by_default == {"frequency"}


# --- buffer.py: offline drain semantics -----------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_append_peek_commit_roundtrip(tmp_path):
    buf = buffer.DiskBuffer(tmp_path / "b.ndjson", max_rows=1000, max_age_h=72)
    now = _iso(datetime.now(timezone.utc))
    items = [("electrical", {"ts_utc": "t1", "phase": "1p", "frequency_hz": 50.0}),
             ("weather", {"time": "t2", "temp": 14.0})]
    buf.append(items, now)
    assert buf.count() == 2
    peeked = buf.peek(10)
    assert peeked[0][0] == "electrical" and peeked[1][0] == "weather"
    buf.commit(1)                       # ack the first only
    assert buf.count() == 1
    assert buf.peek(10)[0][1]["temp"] == 14.0   # remaining is the weather row, order preserved


def test_prune_drops_old_and_caps_rows(tmp_path):
    buf = buffer.DiskBuffer(tmp_path / "b.ndjson", max_rows=3, max_age_h=1)
    old = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
    fresh = _iso(datetime.now(timezone.utc))
    buf.append([("electrical", {"ts_utc": "old"})], old)
    buf.append([("electrical", {"ts_utc": f"n{i}"}) for i in range(5)], fresh)  # noqa
    dropped = buf.prune(datetime.now(timezone.utc))
    assert dropped >= 3                 # 1 aged out + 2 over the 3-row cap
    assert buf.count() == 3


def test_corrupt_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "b.ndjson"
    buf = buffer.DiskBuffer(path, max_rows=1000, max_age_h=72)
    buf.append([("electrical", {"ts_utc": "t1"})], _iso(datetime.now(timezone.utc)))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    # peek must skip the bad line and still return the good one
    assert len(buf.peek(10)) == 1
