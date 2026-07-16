from __future__ import annotations

from pathlib import Path

from tests.conftest import read_all_csv, register


def _auth(node) -> dict:
    return {"Authorization": f"Bearer {node['token']}"}


def test_unconsented_channel_rejected(client):
    # Node consented to frequency only; a power_w value must be rejected, not staged.
    node = register(client, channels=["frequency_hz"])
    batch = {
        "node_id": node["node_id"],
        "electrical": [
            {"ts_utc": "2026-07-16T14:32:05Z", "phase": "1p", "frequency_hz": 50.0, "power_w": 1234.0},
        ],
    }
    r = client.post("/v1/samples", json=batch, headers=_auth(node))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 0
    assert body["rejected"] and "power_w" in body["rejected"][0]["reason"]
    assert read_all_csv(client.gw_settings.staging_dir, "electrical") == []


def test_consented_channels_accepted(client):
    node = register(client, channels=["frequency_hz", "voltage_v"])
    batch = {
        "node_id": node["node_id"],
        "electrical": [
            {"ts_utc": "2026-07-16T14:32:05Z", "phase": "1p", "frequency_hz": 50.0, "voltage_v": 241.3},
        ],
    }
    r = client.post("/v1/samples", json=batch, headers=_auth(node))
    assert r.json()["accepted"] == 1


def test_dedupe_within_window(client):
    node = register(client, channels=["frequency_hz"])
    row = {"ts_utc": "2026-07-16T14:32:05Z", "phase": "1p", "frequency_hz": 50.0}
    batch = {"node_id": node["node_id"], "electrical": [row, dict(row)]}  # same key twice
    r = client.post("/v1/samples", json=batch, headers=_auth(node))
    body = r.json()
    assert body["accepted"] == 1 and body["duplicates"] == 1
    # re-send the same batch: all duplicates
    r2 = client.post("/v1/samples", json=batch, headers=_auth(node))
    assert r2.json()["accepted"] == 0 and r2.json()["duplicates"] == 2


def test_postcode_never_reaches_staging(client):
    # Register data-share with a postcode; push a sample; assert the CSV never contains the postcode
    # (or any private field). The staging projection is allow-list only.
    node = register(client, channels=["frequency_hz"], loc_tier="data_share", postcode="BS1 5AH")
    assert node["loc_ref"] == "GSP_SOUTH_WEST"  # derived key is fine to expose
    batch = {"node_id": node["node_id"],
             "electrical": [{"ts_utc": "2026-07-16T14:32:05Z", "phase": "1p", "frequency_hz": 50.0}]}
    client.post("/v1/samples", json=batch, headers=_auth(node))

    staging_dir: Path = client.gw_settings.staging_dir
    # scan every staged byte for the postcode and the token
    blob = ""
    for p in staging_dir.rglob("*.csv"):
        blob += p.read_text(encoding="utf-8")
    assert "BS1" not in blob and "BS1 5AH" not in blob
    assert node["token"] not in blob
    rows = read_all_csv(staging_dir, "electrical")
    assert rows and "postcode" not in rows[0] and "loc_ref" in rows[0]


def test_revoke_consent_blocks_channel(client):
    node = register(client, channels=["frequency_hz", "voltage_v"])
    headers = _auth(node)
    # revoke voltage
    r = client.patch("/v1/node", json={"node_id": node["node_id"], "channels": ["frequency_hz"]},
                     headers=headers)
    assert r.status_code == 200
    batch = {"node_id": node["node_id"],
             "electrical": [{"ts_utc": "2026-07-16T14:33:05Z", "phase": "1p", "voltage_v": 240.0}]}
    r2 = client.post("/v1/samples", json=batch, headers=headers)
    assert r2.json()["accepted"] == 0 and r2.json()["rejected"]
