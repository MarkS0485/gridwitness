from __future__ import annotations

from tests.conftest import register


def test_samples_without_token_401(client):
    node = register(client)
    r = client.post("/v1/samples", json={"node_id": node["node_id"], "electrical": []})
    assert r.status_code == 401


def test_wrong_token_for_node_401(client):
    a = register(client)
    b = register(client)
    # Present b's token but claim to be node a -> must fail.
    r = client.post(
        "/v1/samples",
        json={"node_id": a["node_id"], "electrical": []},
        headers={"Authorization": f"Bearer {b['token']}"},
    )
    assert r.status_code == 401


def test_unknown_node_404(client):
    node = register(client)
    r = client.post(
        "/v1/samples",
        json={"node_id": "does-not-exist", "electrical": []},
        headers={"Authorization": f"Bearer {node['token']}"},
    )
    assert r.status_code == 404


def test_delete_node_then_gone(client):
    node = register(client)
    headers = {"Authorization": f"Bearer {node['token']}"}
    r = client.request("DELETE", "/v1/node", json={"node_id": node["node_id"]}, headers=headers)
    assert r.status_code == 200 and r.json()["deleted"] is True
    # subsequent use of the node fails (token deleted, node marked deleted)
    r2 = client.post("/v1/samples", json={"node_id": node["node_id"], "electrical": []}, headers=headers)
    assert r2.status_code in (401, 404)
