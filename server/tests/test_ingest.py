from __future__ import annotations

from tests.conftest import read_all_csv, register


def _auth(node) -> dict:
    return {"Authorization": f"Bearer {node['token']}"}


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db_ok"] is True


def test_register_then_samples_lands_csv(client):
    node = register(client, channels=["frequency_hz"])
    batch = {
        "node_id": node["node_id"],
        "client_send_ts": "2026-07-16T14:32:35.010Z",
        "electrical": [
            {"ts_utc": "2026-07-16T14:32:05.250Z", "ts_source": "device",
             "phase": "1p", "frequency_hz": 49.998},
            {"ts_utc": "2026-07-16T14:32:06.250Z", "ts_source": "device",
             "phase": "1p", "frequency_hz": 50.001},
        ],
    }
    r = client.post("/v1/samples", json=batch, headers=_auth(node))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 2 and body["duplicates"] == 0
    assert "server_receive_ts" in body

    rows = read_all_csv(client.gw_settings.staging_dir, "electrical")
    assert len(rows) == 2
    assert rows[0]["node_id"] == node["node_id"]
    assert rows[0]["frequency_hz"] == "49.998"
    assert rows[0]["loc_tier"] == "anon"


def test_time_echo(client):
    r = client.post("/v1/time-echo", json={"client_send": "2026-07-16T14:32:35.010Z"})
    assert r.status_code == 200
    body = r.json()
    assert body["client_send"] == "2026-07-16T14:32:35.010Z"
    assert body["server_receive"].endswith("Z")


def test_weather_row_lands(client):
    node = register(client, channels=["temp", "rhum"])
    batch = {
        "node_id": node["node_id"],
        "weather": [
            {"time": "2026-07-16T14:00:00Z", "ts_source": "ha_receive", "temp": 14.2, "rhum": 81},
        ],
    }
    r = client.post("/v1/samples", json=batch, headers=_auth(node))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1
    rows = read_all_csv(client.gw_settings.staging_dir, "weather")
    assert len(rows) == 1 and rows[0]["temp"] == "14.2"


def test_implausible_frequency_rejected_at_validation(client):
    node = register(client, channels=["frequency_hz"])
    batch = {"node_id": node["node_id"],
             "electrical": [{"ts_utc": "2026-07-16T14:32:05Z", "phase": "1p", "frequency_hz": 999}]}
    r = client.post("/v1/samples", json=batch, headers=_auth(node))
    assert r.status_code == 400
