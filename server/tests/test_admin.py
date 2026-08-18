"""Internal admin API: account-linked provisioning, listing, consent change, GDPR erasure.

These exercise the portal-facing surface. The public register/ingest path is covered elsewhere and
must keep working with no internal credential — asserted here too, so the two paths can't drift.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gridwitness_server.config import Settings
from gridwitness_server.main import create_app

SECRET = "test-internal-secret"
HDR = {"X-GW-Internal": SECRET}
REF = "account-abc"


@pytest.fixture()
def admin_client(tmp_path: Path) -> TestClient:
    data = tmp_path / "server_data"
    settings = Settings(
        data_dir=data,
        db_path=data / "gridwitness.db",
        staging_dir=data / "staging",
        geoip_mmdb=None,
        rate_rows_per_min=6000,
        internal_key=SECRET,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _provision(client: TestClient, contributor_ref: str = REF, **overrides) -> dict:
    body = {
        "channels": ["frequency_hz"],
        "loc_tier": "anon",
        "device_type": "portal_test",
        "contributor_ref": contributor_ref,
    }
    body.update(overrides)
    r = client.post("/v1/register", json=body, headers=HDR)
    assert r.status_code == 201, r.text
    return r.json()


def test_provision_requires_internal_credential(admin_client):
    # contributor_ref set but no/invalid internal header -> refused, no node created.
    body = {"channels": ["frequency_hz"], "loc_tier": "anon", "contributor_ref": REF}
    assert admin_client.post("/v1/register", json=body).status_code == 401
    assert admin_client.post(
        "/v1/register", json=body, headers={"X-GW-Internal": "wrong"}
    ).status_code == 401


def test_public_register_still_open_without_credential(admin_client):
    # No contributor_ref -> the HA/public path, no internal credential needed.
    r = admin_client.post(
        "/v1/register", json={"channels": ["frequency_hz"], "loc_tier": "anon"}
    )
    assert r.status_code == 201
    assert r.json()["token"]


def test_list_nodes_by_contributor(admin_client):
    a = _provision(admin_client, device_type="meter_a")
    b = _provision(admin_client, device_type="meter_b", channels=["frequency_hz", "voltage_v"])
    _provision(admin_client, contributor_ref="someone-else")

    r = admin_client.get("/v1/admin/nodes", params={"contributor_ref": REF}, headers=HDR)
    assert r.status_code == 200
    nodes = r.json()
    ids = {n["node_id"] for n in nodes}
    assert ids == {a["node_id"], b["node_id"]}          # not the other account's node
    assert all("token" not in n for n in nodes)         # tokens never leave the server
    by_id = {n["node_id"]: n for n in nodes}
    assert by_id[b["node_id"]]["channels"] == ["frequency_hz", "voltage_v"]


def test_list_requires_credential(admin_client):
    _provision(admin_client)
    assert admin_client.get("/v1/admin/nodes", params={"contributor_ref": REF}).status_code == 401


def test_admin_disabled_when_no_key(client):
    # `client` fixture builds a server with internal_key unset -> admin surface is 404.
    assert client.get(
        "/v1/admin/nodes", params={"contributor_ref": REF}, headers=HDR
    ).status_code == 404


def test_patch_consent(admin_client):
    node = _provision(admin_client)
    r = admin_client.patch(
        f"/v1/admin/node/{node['node_id']}",
        params={"contributor_ref": REF},
        json={"channels": ["frequency_hz", "voltage_v"]},
        headers=HDR,
    )
    assert r.status_code == 200
    nodes = admin_client.get(
        "/v1/admin/nodes", params={"contributor_ref": REF}, headers=HDR
    ).json()
    assert nodes[0]["channels"] == ["frequency_hz", "voltage_v"]


def test_ownership_enforced_on_patch_and_delete(admin_client):
    node = _provision(admin_client)  # owned by REF
    wrong = {"contributor_ref": "not-the-owner"}
    assert admin_client.patch(
        f"/v1/admin/node/{node['node_id']}", params=wrong, json={"channels": ["voltage_v"]},
        headers=HDR,
    ).status_code == 404
    assert admin_client.request(
        "DELETE", f"/v1/admin/node/{node['node_id']}", params=wrong, headers=HDR
    ).status_code == 404


def test_delete_erases_and_tombstones(admin_client):
    node = _provision(admin_client)
    r = admin_client.request(
        "DELETE", f"/v1/admin/node/{node['node_id']}", params={"contributor_ref": REF}, headers=HDR
    )
    assert r.status_code == 200 and r.json()["deleted"] is True
    # gone from the account listing
    nodes = admin_client.get(
        "/v1/admin/nodes", params={"contributor_ref": REF}, headers=HDR
    ).json()
    assert nodes == []
    # tombstone recorded (honoured by the GDA acquirer)
    db = admin_client.app.state.db
    with db._lock:
        row = db._conn.execute(
            "SELECT 1 FROM tombstones WHERE node_id=?", (node["node_id"],)
        ).fetchone()
    assert row is not None
