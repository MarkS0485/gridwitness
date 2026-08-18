"""Parser robustness across vendor CSV shapes. No server/staging — just parsers.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parsers import parse_csv  # noqa: E402


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_single_phase_comma(tmp_path):
    res = parse_csv(_write(tmp_path, "a.csv",
        "Timestamp,Vrms,Frequency\n2026-01-01T00:00:00Z,240.1,50.01\n"))
    assert res.kept == 1
    r = res.rows[0]
    assert r.phase == "1p" and r.voltage_v == 240.1 and r.frequency_hz == 50.01


def test_current_and_power_columns_ignored(tmp_path):
    res = parse_csv(_write(tmp_path, "a.csv",
        "Time,Voltage,Current,Power,Frequency\n2026-01-01 00:00:00,230,10,2300,50.0\n"))
    r = res.rows[0]
    # Only voltage + frequency survive; current/power are never even read into the row.
    assert r.voltage_v == 230 and r.frequency_hz == 50.0
    assert not hasattr(r, "current_a")


def test_three_phase_maps_to_L1_L2_L3(tmp_path):
    res = parse_csv(_write(tmp_path, "a.csv",
        "Timestamp,V1,V2,V3,Freq\n2026-01-01T00:00:00Z,230,231,229,50.0\n"))
    phases = {r.phase: r.voltage_v for r in res.rows}
    assert phases == {"L1": 230.0, "L2": 231.0, "L3": 229.0}
    # Frequency attaches to L1 only, not duplicated across phases.
    freqs = [r.frequency_hz for r in res.rows if r.frequency_hz is not None]
    assert freqs == [50.0]


def test_european_date_and_semicolon(tmp_path):
    res = parse_csv(_write(tmp_path, "a.csv",
        "Date/Time;Urms;Frequency\n2026-01-15T08:30:00Z;238,5;49,98\n"))
    # semicolon-delimited, comma decimal — a common Chauvin Arnoux / Janitza style.
    assert res.kept == 1
    r = res.rows[0]
    assert r.voltage_v == 238.5 and r.frequency_hz == 49.98


def test_out_of_band_values_dropped(tmp_path):
    res = parse_csv(_write(tmp_path, "a.csv",
        "Timestamp,Vrms,Frequency\n"
        "2026-01-01T00:00:00Z,240,50.0\n"      # good
        "2026-01-01T00:00:01Z,999,50.0\n"      # voltage implausible -> voltage dropped, freq kept
        "2026-01-01T00:00:02Z,240,12.0\n"      # frequency out of band -> freq dropped, voltage kept
        "bad-timestamp,240,50.0\n"))           # unparseable ts -> whole row dropped
    assert res.dropped == 1  # only the bad-timestamp row is fully dropped
    vals = [(r.voltage_v, r.frequency_hz) for r in res.rows]
    assert (240.0, 50.0) in vals
    assert (None, 50.0) in vals   # implausible voltage nulled
    assert (240.0, None) in vals  # out-of-band frequency nulled


def test_no_usable_columns(tmp_path):
    res = parse_csv(_write(tmp_path, "a.csv", "colX,colY\n1,2\n"))
    assert res.rows == [] and res.note
