"""Survey-file upload + account export.

Covers the FAST portal-facing path (register a survey node, stash raw files + manifest) and the
data-portability export. The parse step is the out-of-band survey_ingest worker and is tested there.

Load-bearing guarantee asserted here: a data-share postcode reaches the private DB but NEVER the
manifest or any file the export could hand back as if it were shareable — postcode is not staged.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gridwitness_server.config import Settings
from gridwitness_server.main import create_app

SECRET = "test-internal-secret"
HDR = {"X-GW-Internal": SECRET}
REF = "account-abc"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "server_data"
    return Settings(
        data_dir=data,
        db_path=data / "gridwitness.db",
        staging_dir=data / "staging",
        geoip_mmdb=None,
        rate_rows_per_min=6000,
        internal_key=SECRET,
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as c:
        c.gw_settings = settings
        yield c


def _upload(client: TestClient, files, **form) -> dict:
    data = {"contributor_ref": REF, "label": "Acme Ltd survey", "loc_tier": "region",
            "region": "GSP_LONDON", "device_type": "Fluke 1770"}
    data.update(form)
    r = client.post("/v1/survey/upload", data=data, files=files, headers=HDR)
    assert r.status_code == 200, r.text
    return r.json()


def _csv_bytes() -> bytes:
    return b"Timestamp,Vrms,Frequency\n2026-01-01T00:00:00Z,240.1,50.01\n"


def test_upload_requires_internal_credential(client):
    files = [("files", ("a.csv", _csv_bytes(), "text/csv"))]
    r = client.post("/v1/survey/upload",
                    data={"contributor_ref": REF, "label": "x", "region": "GSP_LONDON"},
                    files=files)
    assert r.status_code == 401


def test_upload_registers_node_and_stashes_files(client):
    files = [
        ("files", ("survey1.csv", _csv_bytes(), "text/csv")),
        ("files", ("survey2.txt", _csv_bytes(), "text/plain")),
    ]
    out = _upload(client, files)
    assert out["accepted"] == 2 and out["rejected"] == []
    node_id = out["node_id"]

    # The node exists, owned by REF, consenting only to the two safe channels, tagged as a survey.
    nodes = client.get("/v1/admin/nodes", params={"contributor_ref": REF}, headers=HDR).json()
    assert len(nodes) == 1
    assert nodes[0]["channels"] == ["frequency_hz", "voltage_v"]
    assert nodes[0]["producer"] == "gridwitness-survey"

    # Raw files + manifest landed in the inbox, queued for the worker.
    inbox = client.gw_settings.surveys_inbox / node_id
    stored = sorted(p.name for p in inbox.iterdir())
    assert "manifest.json" in stored
    manifest = json.loads((inbox / "manifest.json").read_text())
    assert manifest["status"] == "queued"
    assert len(manifest["files"]) == 2


def test_bad_extensions_rejected_good_ones_kept(client):
    files = [
        ("files", ("ok.csv", _csv_bytes(), "text/csv")),
        ("files", ("bad.exe", b"MZ", "application/octet-stream")),
    ]
    out = _upload(client, files)
    assert out["accepted"] == 1
    assert len(out["rejected"]) == 1 and "bad.exe" in out["rejected"][0]["filename"]


def test_surveys_reject_anonymous(client):
    files = [("files", ("a.csv", _csv_bytes(), "text/csv"))]
    r = client.post("/v1/survey/upload",
                    data={"contributor_ref": REF, "label": "x", "loc_tier": "anon"},
                    files=files, headers=HDR)
    assert r.status_code == 400  # a voltage trace with no location has no research value


def test_postcode_never_reaches_manifest_or_inbox(client):
    """data_share postcode goes to the private DB only — not the manifest, not any inbox file."""
    postcode = "BS1 5AH"
    files = [("files", ("a.csv", _csv_bytes(), "text/csv"))]
    out = _upload(client, files, loc_tier="data_share", region="", postcode=postcode)
    node_id = out["node_id"]

    # It IS in the private DB (that's where owner/erasure needs it).
    db = client.app.state.db
    with db._lock:
        row = db._conn.execute(
            "SELECT postcode FROM node_private WHERE node_id=?", (node_id,)
        ).fetchone()
    assert row["postcode"] == postcode

    # It is NOWHERE under the inbox — not the manifest, not any stored file.
    inbox = client.gw_settings.surveys_inbox / node_id
    for path in inbox.rglob("*"):
        if path.is_file():
            assert postcode not in path.read_text(errors="ignore"), f"postcode leaked into {path.name}"


def test_export_bundles_owned_files_only(client):
    # Upload one survey for REF and one for another account.
    mine = _upload(client, [("files", ("mine.csv", _csv_bytes(), "text/csv"))])
    _upload(client, [("files", ("theirs.csv", _csv_bytes(), "text/csv"))],
            contributor_ref="someone-else")

    r = client.get("/v1/account/export", params={"contributor_ref": REF}, headers=HDR)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "README.txt" in names and "manifest.json" in names
    # My survey's file is present; the other account's node id never appears.
    assert any(n.startswith(mine["node_id"] + "/") for n in names)
    manifest = json.loads(zf.read("manifest.json"))
    assert {s["node_id"] for s in manifest["surveys"]} == {mine["node_id"]}


def test_export_requires_internal_credential(client):
    assert client.get("/v1/account/export", params={"contributor_ref": REF}).status_code == 401
