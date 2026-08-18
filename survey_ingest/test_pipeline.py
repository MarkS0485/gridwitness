"""End-to-end: portal upload -> survey_ingest worker -> CSV staging.

Runs the real FastAPI upload endpoint and the real worker against one shared temp staging tree, so
this is the closest thing to production short of the lake. The load-bearing assertion is at the
staging layer: a data-share postcode reaches the private DB but NEVER the staged electrical CSV that
the GDA acquirer will read — the same guarantee test_survey.py makes for the inbox, now proven for
the parsed output too.

Run:  python -m pytest test_pipeline.py       (from survey_ingest/)
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "server"))
sys.path.insert(0, str(_HERE))

from gridwitness_server.config import Settings          # noqa: E402
from gridwitness_server.db import Database              # noqa: E402
from gridwitness_server.main import create_app          # noqa: E402
from gridwitness_server.staging import StagingWriter    # noqa: E402
import survey_ingest as worker                          # noqa: E402

SECRET = "test-internal-secret"
HDR = {"X-GW-Internal": SECRET}
REF = "account-xyz"
POSTCODE = "BS1 5AH"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "server_data"
    return Settings(data_dir=data, db_path=data / "gridwitness.db",
                    staging_dir=data / "staging", geoip_mmdb=None,
                    rate_rows_per_min=6000, internal_key=SECRET)


def _staged_electrical(settings: Settings) -> list[dict]:
    rows: list[dict] = []
    for p in sorted((settings.staging_dir / "electrical").rglob("*.csv")):
        with p.open(newline="", encoding="utf-8") as fh:
            rows.extend(csv.DictReader(fh))
    return rows


def _upload_and_drain(settings: Settings, csv_text: bytes, **form) -> str:
    app = create_app(settings)
    with TestClient(app) as c:
        data = {"contributor_ref": REF, "label": "Site survey", "loc_tier": "data_share",
                "postcode": POSTCODE, "device_type": "Hioki PQ3100"}
        data.update(form)
        r = c.post("/v1/survey/upload", data=data,
                   files=[("files", ("trend.csv", csv_text, "text/csv"))], headers=HDR)
        assert r.status_code == 200, r.text
        node_id = r.json()["node_id"]
    # Drain with a fresh db/staging handle against the same tree (as the scheduled worker would).
    db = Database(settings.db_path)
    staging = StagingWriter(settings.staging_dir)
    try:
        worker.drain(settings, db, staging)
    finally:
        db.close()
    return node_id


def test_pipeline_stages_freq_and_voltage(settings):
    csv_text = (b"Timestamp,Vrms,Frequency,Current\n"
                b"2026-02-01T12:00:00Z,241.2,50.02,8.1\n"
                b"2026-02-01T12:00:01Z,240.7,49.98,8.0\n")
    node_id = _upload_and_drain(settings, csv_text)

    rows = _staged_electrical(settings)
    assert len(rows) == 2
    assert all(r["node_id"] == node_id for r in rows)
    assert rows[0]["voltage_v"] and rows[0]["frequency_hz"]
    # Current was in the file but is NOT a survey channel — it must never be staged.
    assert rows[0]["current_a"] in ("", None)


def test_postcode_never_reaches_staged_csv(settings):
    """The whole point: the postcode is in the private DB, never in the acquirer-facing CSV."""
    csv_text = b"Timestamp,Vrms,Frequency\n2026-02-01T12:00:00Z,241.2,50.02\n"
    node_id = _upload_and_drain(settings, csv_text)

    db = Database(settings.db_path)
    with db._lock:
        row = db._conn.execute(
            "SELECT postcode FROM node_private WHERE node_id=?", (node_id,)
        ).fetchone()
    db.close()
    assert row["postcode"] == POSTCODE  # kept privately for ownership/erasure

    for p in (settings.staging_dir / "electrical").rglob("*.csv"):
        assert POSTCODE not in p.read_text(), f"postcode leaked into {p}"
    # And the loc_ref that DID stage is the coarse derived region, not the postcode.
    rows = _staged_electrical(settings)
    assert rows and rows[0]["loc_ref"] and POSTCODE not in rows[0]["loc_ref"]


def test_pqdif_defers_when_no_converter(settings):
    """A PQDIF file (no converter in this env) stays queued in the inbox; CSVs still process."""
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.post("/v1/survey/upload",
                   data={"contributor_ref": REF, "label": "mixed", "loc_tier": "region",
                         "region": "GSP_LONDON", "device_type": "Fluke 1770"},
                   files=[("files", ("trend.csv", b"Timestamp,Vrms,Frequency\n2026-03-01T00:00:00Z,240,50.0\n", "text/csv")),
                          ("files", ("scope.pqd", b"\x00PQDIF-binary", "application/octet-stream"))],
                   headers=HDR)
        assert r.status_code == 200, r.text
        node_id = r.json()["node_id"]

    db = Database(settings.db_path)
    staging = StagingWriter(settings.staging_dir)
    try:
        results = worker.drain(settings, db, staging)
    finally:
        db.close()

    assert results[0]["status"] == "pqdif_pending"
    assert any(p.endswith("scope.pqd") for p in results[0]["pending"])
    # The CSV row DID stage; the PQDIF is still queued for local conversion.
    assert _staged_electrical(settings)
    inbox = settings.surveys_inbox / node_id
    assert any(p.name.endswith("scope.pqd") for p in inbox.iterdir())
    assert not any(p.name.endswith("trend.csv") for p in inbox.iterdir())  # CSV handled + archived


def test_withdrawal_purges_archive(settings):
    csv_text = b"Timestamp,Vrms,Frequency\n2026-02-01T12:00:00Z,241.2,50.02\n"
    node_id = _upload_and_drain(settings, csv_text)
    archive = settings.surveys_archive / node_id
    assert archive.is_dir() and any(archive.glob("extracted_*.csv"))

    # Withdraw via the admin API; raw files must be gone immediately (lake drop is the tombstone).
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.request("DELETE", f"/v1/admin/node/{node_id}",
                      params={"contributor_ref": REF}, headers=HDR)
        assert r.status_code == 200 and r.json()["deleted"] is True
    assert not archive.exists()
    assert not (settings.surveys_inbox / node_id).exists()
