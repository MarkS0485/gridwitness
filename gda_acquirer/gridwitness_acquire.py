#!/usr/bin/env python3
"""GridWitness -> GDA lake acquirer.

Reads the ingest server's CSV staging tree (the only contract between server and lake) and lands two
GDA datasets, following the gridradar acquirer conventions exactly:

    DataSources/GridWitness/Parquet/gw_electrical/year=/week=/gw_electrical_YYYYwWW.parquet
    DataSources/GridWitness/Parquet/gw_weather/year=/week=/gw_weather_YYYYwWW.parquet

Conventions mirrored from Ingest/gridradar/gridradar_acquire.py:
  * GDA root discovery by marker, then `sys.path.insert` so `Scripts.*` import.
  * hive year=/week= partitioning via Scripts.parquet_partitioning helpers.
  * atomic write (.tmp + os.replace); MERGE preferring non-null (new.combine_first(old)).
  * single-instance localhost lock on a FRESH port (47830).
  * horizon clamp via Scripts.horizon.ingest_cutoff (lake lags real time; give-back card is live).
  * best-effort Scripts.schema_gate.check_written after each write.
  * `--selftest` does an offline CSV->parquet->read-back round trip in a temp dir, never the lake.
  * exits non-zero when it wrote 0 rows where data was expected (so an orchestrator sees a no-op).

This file is the version-controlled copy. Deployment copies it to
D:\\Work\\GDA\\v1\\Ingest\\gridwitness\\gridwitness_acquire.py (see README.md). It is NOT run from
inside the GridWitness repo in production.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LOCK_PORT = 47830  # fresh, distinct from gridradar(47829)/powergridfreq(47831)/meteostat(47824)

ELECTRICAL_DB = "gw_electrical"
WEATHER_DB = "gw_weather"
ELECTRICAL_KEY = ["ts_utc", "node_id", "phase"]
WEATHER_KEY = ["time", "node_id"]

_HERE = Path(__file__).resolve().parent


# --- GDA root discovery + helper import -----------------------------------------------------------

def find_gda_root(explicit: str | None) -> Path:
    """Locate the GDA lake root (contains DataSchema.json / DataSources).

    Order: --gda-root/GDA_ROOT, then walk parents for the marker (works once deployed inside GDA),
    then a dev fallback of D:/Work/GDA/v1 so --selftest is runnable from the GridWitness repo.
    """
    if explicit:
        return Path(explicit)
    if os.environ.get("GDA_ROOT"):
        return Path(os.environ["GDA_ROOT"])
    for p in _HERE.parents:
        if (p / "DataSchema.json").exists() or (p / "DataSources").is_dir():
            return p
    dev = Path("D:/Work/GDA/v1")
    if dev.exists():
        return dev
    raise SystemExit("[fatal] could not locate GDA root; pass --gda-root or set GDA_ROOT")


def load_helpers(root: Path):
    """Import the shared GDA write helpers. Returns a dict of callables."""
    sys.path.insert(0, str(root))
    from Scripts.parquet_partitioning import _build_partition_frame, determine_partition_columns

    helpers = {
        "build_partition_frame": _build_partition_frame,
        "determine_partition_columns": determine_partition_columns,
    }
    try:
        from Scripts.horizon import ingest_cutoff
        helpers["ingest_cutoff"] = ingest_cutoff
    except Exception:  # noqa: BLE001 - horizon is optional in dev
        helpers["ingest_cutoff"] = None
    try:
        from Scripts.schema_gate import check_written
        helpers["check_written"] = check_written
    except Exception:  # noqa: BLE001 - gate is best-effort, never fatal
        helpers["check_written"] = lambda *_a, **_k: None
    return helpers


# --- single instance ------------------------------------------------------------------------------

def single_instance() -> socket.socket | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        print(f"[lock] another gridwitness_acquire holds :{LOCK_PORT}; exiting")
        return None


# --- staging read ---------------------------------------------------------------------------------

def read_staging(staging_dir: Path, kind: str, since_hour: str | None) -> list[dict]:
    """Read all hour CSVs for a kind newer than the state cursor. Returns list of row dicts."""
    base = staging_dir / kind
    if not base.exists():
        return []
    rows: list[dict] = []
    for day_dir in sorted(base.glob("dt=*")):
        for hour_csv in sorted(day_dir.glob("*.csv")):
            hour_key = f"{day_dir.name[3:]}T{hour_csv.stem}"  # YYYY-MM-DDTHH
            if since_hour is not None and hour_key <= since_hour:
                continue
            with hour_csv.open(newline="", encoding="utf-8") as fh:
                rows.extend(dict(r) for r in csv.DictReader(fh))
    return rows


def latest_hour(staging_dir: Path, kind: str) -> str | None:
    base = staging_dir / kind
    if not base.exists():
        return None
    best: str | None = None
    for day_dir in sorted(base.glob("dt=*")):
        for hour_csv in sorted(day_dir.glob("*.csv")):
            hour_key = f"{day_dir.name[3:]}T{hour_csv.stem}"
            if best is None or hour_key > best:
                best = hour_key
    return best


# --- frames ---------------------------------------------------------------------------------------

def _to_float(v):
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def frame_electrical(rows: list[dict]):
    import pandas as pd

    if not rows:
        return pd.DataFrame()
    cols = ["ts_utc", "node_id", "phase", "ts_source", "voltage_v", "current_a", "power_w",
            "power_factor", "frequency_hz", "phase_angle_deg", "device_type", "firmware",
            "cadence_ms", "loc_tier", "loc_ref"]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    for c in ["voltage_v", "current_a", "power_w", "power_factor", "frequency_hz", "phase_angle_deg"]:
        df[c] = df[c].map(_to_float)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_utc", "node_id"])
    return df[cols]


def frame_weather(rows: list[dict]):
    import pandas as pd

    if not rows:
        return pd.DataFrame()
    cols = ["time", "node_id", "ts_source", "temp", "rhum", "wspd", "wdir", "pres", "prcp",
            "solar_radiation_w_m2", "uv", "device_type", "loc_tier", "loc_ref", "cell_id"]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    for c in ["temp", "rhum", "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv"]:
        df[c] = df[c].map(_to_float)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time", "node_id"])
    return df[cols]


# --- write path (atomic + non-null MERGE), mirrors gridradar _write() ------------------------------

def write_dataset(df, *, database: str, key: list[str], ts_col: str, outroot: Path, helpers) -> int:
    import pandas as pd

    if df is None or df.empty:
        return 0
    outdir = outroot / "DataSources" / "GridWitness" / "Parquet" / database
    part_cols = helpers["determine_partition_columns"](len(df))
    partitioned, effective = helpers["build_partition_frame"](
        df, partition_columns=part_cols, timestamp_column=ts_col, database_name=database
    )
    written = 0
    for (yr, wk), group in partitioned.groupby(["year", "week"], sort=True):
        yw = f"{int(yr)}w{int(wk):02d}"
        target_dir = outdir / f"year={int(yr)}" / f"week={int(wk):02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        final = target_dir / f"{database}_{yw}.parquet"
        tmp = target_dir / f".{database}_{yw}.parquet.tmp"

        payload = group.copy()
        if final.exists():
            try:
                prev = pd.read_parquet(final)
            except Exception:  # noqa: BLE001 - never clobber on a read error (GDA-M1)
                print(f"[skip] unreadable {final}, not overwriting")
                continue
            new = payload.drop_duplicates(subset=key, keep="last").set_index(key)
            old = prev.drop_duplicates(subset=key, keep="last").set_index(key)
            merged = new.combine_first(old).reset_index()          # MERGE prefers non-null (GDA-H1)
            payload = merged.reindex(columns=payload.columns)
        payload = payload.sort_values(key)
        payload.to_parquet(tmp, index=False)
        os.replace(tmp, final)                                     # atomic
        helpers["check_written"](f"GridWitness/{database}", final)
        written += len(group)
    return written


def _clamp_horizon(df, ts_col: str, helpers):
    """Hold the lake behind real time (Scripts.horizon.ingest_cutoff). Newer rows stay in staging."""
    import pandas as pd

    if df is None or df.empty or helpers.get("ingest_cutoff") is None:
        return df
    cutoff = helpers["ingest_cutoff"]()
    if not isinstance(cutoff, datetime):
        return df
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return df[df[ts_col] <= pd.Timestamp(cutoff)]


# --- state ----------------------------------------------------------------------------------------

def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)


# --- main ---------------------------------------------------------------------------------------

def run(staging_dir: Path, outroot: Path, state_path: Path, helpers, *, apply_horizon: bool) -> int:
    state = load_state(state_path)
    total = 0
    for kind, db, key, ts_col in (
        ("electrical", ELECTRICAL_DB, ELECTRICAL_KEY, "ts_utc"),
        ("weather", WEATHER_DB, WEATHER_KEY, "time"),
    ):
        since = state.get(f"{kind}_covered_hour")
        rows = read_staging(staging_dir, kind, since)
        df = frame_electrical(rows) if kind == "electrical" else frame_weather(rows)
        if apply_horizon:
            df = _clamp_horizon(df, ts_col, helpers)
        wrote = write_dataset(df, database=db, key=key, ts_col=ts_col, outroot=outroot, helpers=helpers)
        total += wrote
        newest = latest_hour(staging_dir, kind)
        if newest:
            state[f"{kind}_covered_hour"] = newest
        print(f"[{kind}] read {len(rows)} rows -> wrote {wrote} to {db}")
    save_state(state_path, state)
    return total


def selftest() -> int:
    """Offline CSV -> parquet -> read-back round trip in a temp dir. Never touches the real lake."""
    import pandas as pd

    root = find_gda_root(None)
    helpers = load_helpers(root)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        staging = tmp / "staging"
        (staging / "electrical" / "dt=2026-07-10").mkdir(parents=True)
        (staging / "weather" / "dt=2026-07-10").mkdir(parents=True)
        # electrical CSV
        with (staging / "electrical" / "dt=2026-07-10" / "09.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["node_id", "ts_utc", "ts_source", "phase",
                "voltage_v", "current_a", "power_w", "power_factor", "frequency_hz",
                "phase_angle_deg", "device_type", "firmware", "cadence_ms", "loc_tier", "loc_ref"])
            w.writeheader()
            w.writerow({"node_id": "n1", "ts_utc": "2026-07-10T09:00:00Z", "ts_source": "device",
                        "phase": "1p", "frequency_hz": "49.99", "device_type": "test",
                        "loc_tier": "anon", "loc_ref": ""})
            w.writerow({"node_id": "n1", "ts_utc": "2026-07-10T09:00:01Z", "ts_source": "device",
                        "phase": "1p", "frequency_hz": "50.01", "device_type": "test",
                        "loc_tier": "anon", "loc_ref": ""})
        # weather CSV
        with (staging / "weather" / "dt=2026-07-10" / "09.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["node_id", "time", "ts_source", "temp", "rhum",
                "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv", "device_type",
                "loc_tier", "loc_ref", "cell_id"])
            w.writeheader()
            w.writerow({"node_id": "n1", "time": "2026-07-10T09:00:00Z", "ts_source": "ha_receive",
                        "temp": "14.2", "rhum": "80", "device_type": "test", "loc_tier": "anon",
                        "loc_ref": "", "cell_id": "cell_51.375_-2.625"})

        state_path = tmp / "state.json"
        wrote = run(staging, tmp, state_path, helpers, apply_horizon=False)
        assert wrote == 3, f"expected 3 rows written, got {wrote}"

        def _read_dataset(db: str):
            # Read individual part files and concat — avoids pyarrow inferring the hive year=/week=
            # partition columns (which collide with the same columns stored in-file as provenance).
            root_dir = tmp / "DataSources" / "GridWitness" / "Parquet" / db
            parts = [pd.read_parquet(p) for p in sorted(root_dir.rglob("*.parquet"))]
            return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

        elec = _read_dataset(ELECTRICAL_DB)
        wx = _read_dataset(WEATHER_DB)
        assert len(elec) == 2 and set(elec["node_id"]) == {"n1"}
        assert float(elec["frequency_hz"].min()) == 49.99
        assert "year" in elec.columns and "week" in elec.columns
        assert len(wx) == 1 and wx.iloc[0]["cell_id"] == "cell_51.375_-2.625"

        # idempotency: re-run must not duplicate (MERGE on key)
        state_path.unlink()
        run(staging, tmp, state_path, helpers, apply_horizon=False)
        elec2 = _read_dataset(ELECTRICAL_DB)
        assert len(elec2) == 2, f"idempotency broken: {len(elec2)} rows after re-run"
    print("[selftest] OK — CSV->parquet round trip + idempotent MERGE verified")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GridWitness -> GDA lake acquirer")
    ap.add_argument("--selftest", action="store_true", help="offline round-trip test, no lake writes")
    ap.add_argument("--gda-root", default=None, help="GDA lake root (else GDA_ROOT / auto-discover)")
    ap.add_argument("--staging", default=None, help="staging dir (else from config.json)")
    ap.add_argument("--no-horizon", action="store_true", help="do not clamp to ingest_cutoff")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    root = find_gda_root(args.gda_root)
    helpers = load_helpers(root)

    cfg = {}
    cfg_path = _HERE / "config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text())
    staging_dir = Path(args.staging or cfg.get("staging_dir", ""))
    if not staging_dir or not staging_dir.exists():
        raise SystemExit(f"[fatal] staging dir not found: {staging_dir!r} (set --staging or config.json)")

    lock = single_instance()
    if lock is None:
        return 0
    try:
        state_path = _HERE / "state.json"
        wrote = run(staging_dir, root, state_path, helpers, apply_horizon=not args.no_horizon)
        if wrote == 0:
            print("[warn] wrote 0 rows")
            # Non-zero only if staging had data we failed to land; empty staging is a clean no-op.
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
