from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gridwitness_server.config import Settings
from gridwitness_server.main import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "server_data"
    return Settings(
        data_dir=data,
        db_path=data / "gridwitness.db",
        staging_dir=data / "staging",
        geoip_mmdb=None,
        rate_rows_per_min=6000,
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as c:
        c.gw_settings = settings  # stash for tests that inspect staging
        yield c


def register(client: TestClient, **overrides) -> dict:
    body = {"channels": ["frequency_hz"], "loc_tier": "anon", "device_type": "test_meter"}
    body.update(overrides)
    resp = client.post("/v1/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def read_all_csv(staging_dir: Path, kind: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted((staging_dir / kind).rglob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            rows.extend(csv.DictReader(fh))
    return rows
