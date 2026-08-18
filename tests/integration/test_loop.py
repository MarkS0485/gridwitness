"""End-to-end vertical slice: client contract -> ingest server -> CSV staging -> GDA acquirer -> parquet.

Proves the whole P0 loop (minus the HA runtime, which needs its own harness). Requires pandas +
pyarrow + a reachable GDA root for the partitioning helpers (auto-discovered, or set GDA_ROOT).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "server"))

pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from fastapi.testclient import TestClient  # noqa: E402

from gridwitness_server.config import Settings  # noqa: E402
from gridwitness_server.main import create_app  # noqa: E402


def _load_acquirer():
    path = _REPO / "gda_acquirer" / "gridwitness_acquire.py"
    spec = importlib.util.spec_from_file_location("gw_acquire", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_full_loop_frequency(tmp_path):
    acq = _load_acquirer()
    try:
        gda_root = acq.find_gda_root(None)
        helpers = acq.load_helpers(gda_root)
    except SystemExit:
        pytest.skip("GDA root not available for partitioning helpers")

    # 1. stand up the ingest server on a temp data dir
    data = tmp_path / "server_data"
    settings = Settings(data_dir=data, db_path=data / "gw.db", staging_dir=data / "staging",
                        geoip_mmdb=None, rate_rows_per_min=100000)
    app = create_app(settings)

    with TestClient(app) as client:
        # 2. register a frequency-only anon node (the HA config-flow contract)
        reg = client.post("/v1/register", json={
            "channels": ["frequency_hz"], "loc_tier": "anon", "device_type": "home_assistant",
        })
        assert reg.status_code == 201, reg.text
        node = reg.json()

        # 3. push a batch of frequency samples dated a few days ago (past the horizon)
        rows = [
            {"ts_utc": f"2026-07-10T09:00:{s:02d}Z", "ts_source": "device",
             "phase": "1p", "frequency_hz": 49.9 + s * 0.01}
            for s in range(5)
        ]
        resp = client.post("/v1/samples",
                           json={"node_id": node["node_id"], "electrical": rows},
                           headers={"Authorization": f"Bearer {node['token']}"})
        assert resp.status_code == 200 and resp.json()["accepted"] == 5

    # 4. run the acquirer against the server's real CSV staging dir -> parquet in a temp lake
    lake = tmp_path / "lake"
    state = tmp_path / "state.json"
    wrote = acq.run(settings.staging_dir, lake, state, helpers, apply_horizon=True)
    assert wrote == 5, f"expected 5 rows landed, got {wrote}"

    # 5. the landed parquet carries the crowd frequency, ready for frequency_all_srcs
    import pandas as pd
    parts = list((lake / "DataSources" / "GridWitness" / "Parquet" / "gw_electrical").rglob("*.parquet"))
    assert parts, "no parquet written"
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    assert len(df) == 5
    assert df["node_id"].nunique() == 1
    assert 49.8 < float(df["frequency_hz"].min()) < 50.1
    # privacy: no personal columns crossed the CSV boundary into the lake
    assert not ({"postcode", "token", "lat", "lon"} & set(df.columns))
