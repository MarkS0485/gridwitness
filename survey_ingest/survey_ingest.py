#!/usr/bin/env python3
"""GridWitness survey-file ingester (out-of-band worker).

Companion to the GDA acquirer: a scheduled, single-instance batch process that drains the survey
upload inbox the FastAPI server fills. For each queued survey it:

    1. loads the survey node (skip+purge if it was withdrawn — honours GDPR erasure);
    2. parses every uploaded file, keeping ONLY frequency + voltage (parsers.py);
    3. projects each row through the server's privacy allow-list (project_electrical) and appends it
       to the CSV staging tree — the exact same contract the HA path and the GDA acquirer use;
    4. writes an extracted_*.csv of those rows next to the originals (for the account's data export);
    5. moves the raw originals to archive/ and marks the manifest processed.

It never touches the parquet lake — the GDA acquirer picks the staged rows up on its own cycle. It
reuses the gridwitness_server package for config/db/staging/privacy so there is one source of truth.

Run:  python survey_ingest.py            (drain the inbox once)
      python survey_ingest.py --selftest (offline round-trip in a temp dir, no real data)
Schedule it like the acquirer (see README.md). Single-instance localhost lock on :47832.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Reuse the server package (config/db/staging/privacy/models). Override with GW_SERVER_PATH if the
# worker is deployed somewhere the sibling server/ dir isn't adjacent.
_SERVER = Path(os.environ.get("GW_SERVER_PATH", _HERE.parent / "server"))
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from parsers import parse_file  # noqa: E402  (local module, after sys.path setup)

LOCK_PORT = 47832  # fresh: gridradar 47829 / gw_acquire 47830 / powergridfreq 47831 / survey 47832


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def single_instance() -> "socket.socket | None":
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        print(f"[lock] another survey_ingest holds :{LOCK_PORT}; exiting")
        return None


def _converter() -> str | None:
    """Path to the pqdif2csv .NET tool, if configured/on PATH. None disables PQDIF (CSV still works)."""
    return os.environ.get("GW_PQDIF2CSV") or shutil.which("pqdif2csv")


def clock_qa(rows) -> str | None:
    """Light clock/plausibility check on a survey's frequency series.

    Frequency is grid-global, so a survey's own frequency trace is a free anchor: it should sit in a
    tight band around 50 Hz. A trace that doesn't is a sign of a bad clock or a mislabelled column.
    P1: cross-check against the GB frequency lake at each timestamp to actually correct clock offset;
    for now we only flag an implausible spread so it lands in the manifest note rather than silently.
    """
    freqs = [r.frequency_hz for r in rows if r.frequency_hz is not None]
    if len(freqs) < 10:
        return None
    lo, hi = min(freqs), max(freqs)
    if hi - lo > 2.0:  # GB frequency never legitimately spans >2 Hz within a survey
        return f"wide frequency spread {lo:.2f}-{hi:.2f} Hz; clock/column suspect"
    return None


def process_survey(inbox_dir: Path, settings, db, staging) -> dict:
    """Parse + stage one survey. Returns a small result summary for logging."""
    from gridwitness_server.privacy import ELECTRICAL_CSV_COLUMNS, project_electrical
    from gridwitness_server.models import ElectricalRow

    node_id = inbox_dir.name
    manifest_path = inbox_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    node = db.get_node(node_id)
    if node is None:
        # Withdrawn (or never live) — honour erasure: purge inbox + any archive, stage nothing.
        shutil.rmtree(inbox_dir, ignore_errors=True)
        shutil.rmtree(settings.surveys_archive / node_id, ignore_errors=True)
        return {"node_id": node_id, "status": "purged_withdrawn"}

    consented = node["channels"]  # a set; survey nodes consent to frequency_hz + voltage_v only
    data_files = [p for p in sorted(inbox_dir.iterdir()) if p.is_file() and p.name != "manifest.json"]

    converter = _converter()
    staged_rows: list[dict] = []
    all_parsed = []
    file_reports: list[dict] = []
    handled: list[Path] = []   # parsed + staged this run → move to archive
    deferred: list[Path] = []  # couldn't handle here (PQDIF, no converter) → leave queued in inbox
    for path in data_files:
        res = parse_file(path, converter)
        if res.deferred:
            deferred.append(path)
            file_reports.append({"file": path.name, "status": "pending_conversion", "note": res.note})
            continue
        all_parsed.extend(res.rows)
        for pr in res.rows:
            row = ElectricalRow(
                ts_utc=pr.ts_utc, ts_source="device", phase=pr.phase,
                voltage_v=pr.voltage_v, frequency_hz=pr.frequency_hz,
            )
            # Defence in depth: never stage a channel the node didn't consent to (it can't here, but
            # the same rule the /v1/samples path enforces applies to survey rows too).
            if row.present_channels() - consented:
                continue
            staged_rows.append(project_electrical(row, node))
        handled.append(path)
        file_reports.append({
            "file": path.name, "read": res.read, "kept": res.kept,
            "dropped": res.dropped, "note": res.note,
        })

    accepted, dups = staging.write_electrical(staged_rows)

    # Archive the files we staged (+ the extracted series for the export bundle). A file still in the
    # inbox == not yet staged, which keeps re-runs idempotent: a later Windows run with the converter
    # picks up the deferred PQDIF, stages it, and only then completes the survey.
    archive_dir = settings.surveys_archive / node_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    if staged_rows:
        _write_extracted(archive_dir, ELECTRICAL_CSV_COLUMNS, staged_rows)
    for path in handled:
        shutil.move(str(path), str(archive_dir / path.name))

    note = clock_qa(all_parsed)
    manifest.update({
        "processed_utc": _now_iso(),
        "rows_staged": manifest.get("rows_staged", 0) + accepted,
        "rows_duplicate": dups,
        "files": file_reports,
        "qa_note": note,
    })

    if deferred:
        # PQDIF still needs converting on a Windows host — leave those files + the manifest in the
        # inbox so nothing is lost and it isn't marked done.
        manifest["status"] = "pqdif_pending"
        manifest["pending_files"] = [p.name for p in deferred]
        (inbox_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"node_id": node_id, "status": "pqdif_pending", "rows_staged": accepted,
                "pending": [p.name for p in deferred], "qa_note": note}

    manifest["status"] = "processed"
    (archive_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.rmtree(inbox_dir, ignore_errors=True)
    return {"node_id": node_id, "status": "processed", "rows_staged": accepted,
            "files": len(handled), "qa_note": note}


def _write_extracted(archive_dir: Path, columns: list[str], rows: list[dict]) -> None:
    import csv
    out = archive_dir / f"extracted_{_now_iso().replace(':', '').replace('.', '')}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c) for c in columns})


def drain(settings, db, staging) -> list[dict]:
    inbox_root = settings.surveys_inbox
    if not inbox_root.exists():
        return []
    results = []
    for inbox_dir in sorted(p for p in inbox_root.iterdir() if p.is_dir()):
        try:
            results.append(process_survey(inbox_dir, settings, db, staging))
        except Exception as e:  # noqa: BLE001 - one bad survey must not stop the rest
            print(f"[error] survey {inbox_dir.name}: {e}")
            results.append({"node_id": inbox_dir.name, "status": "error", "error": str(e)})
    return results


def _run() -> int:
    from gridwitness_server.config import get_settings
    from gridwitness_server.db import Database
    from gridwitness_server.staging import StagingWriter

    settings = get_settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    staging = StagingWriter(settings.staging_dir)
    try:
        results = drain(settings, db, staging)
    finally:
        db.close()

    processed = [r for r in results if r["status"] == "processed"]
    total_rows = sum(r.get("rows_staged", 0) for r in processed)
    print(f"[done] surveys={len(results)} processed={len(processed)} rows_staged={total_rows}")
    for r in results:
        print("  ", json.dumps(r))
    return 0


def _selftest() -> int:
    """Offline round trip: a fake Fluke-style CSV → staged electrical rows, in a temp dir only."""
    import tempfile
    from gridwitness_server.config import Settings
    from gridwitness_server.db import Database
    from gridwitness_server.staging import StagingWriter

    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "server_data"
        settings = Settings(data_dir=data, db_path=data / "gw.db",
                            staging_dir=data / "staging", geoip_mmdb=None, rate_rows_per_min=6000)
        settings.ensure_dirs()
        db = Database(settings.db_path)
        from gridwitness_server.auth import new_token
        from gridwitness_server.models import SURVEY_CHANNELS, SURVEY_PRODUCER
        _tok, h = new_token()
        db.create_node(node_id="selftest", token_sha256=h, device_type="Fluke 1770",
                       firmware=None, cadence_ms=None, loc_tier="region", loc_ref="DNO_GSP_LONDON",
                       cell_id=None, channels=list(SURVEY_CHANNELS), postcode=None, raw_region=None,
                       producer=SURVEY_PRODUCER, contributor_ref="acct")
        inbox = settings.surveys_inbox / "selftest"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "manifest.json").write_text(json.dumps({"node_id": "selftest", "status": "queued"}))
        (inbox / "log.csv").write_text(
            "Timestamp,Vrms,Frequency\n"
            "2026-01-01T00:00:00Z,240.1,50.01\n"
            "2026-01-01T00:00:01Z,239.8,49.99\n"
        )
        staging = StagingWriter(settings.staging_dir)
        results = drain(settings, db, staging)
        db.close()

        staged = list((settings.staging_dir / "electrical").rglob("*.csv"))
        ok = results and results[0]["status"] == "processed" and results[0]["rows_staged"] == 2 and staged
        # The archive must hold the extracted series; the inbox must be gone.
        archived = list((settings.surveys_archive / "selftest").glob("extracted_*.csv"))
        ok = ok and archived and not inbox.exists()
        print("[selftest]", "PASS" if ok else "FAIL", json.dumps(results))
        return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Drain the GridWitness survey upload inbox.")
    ap.add_argument("--selftest", action="store_true", help="offline round-trip, no real data")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    lock = single_instance()
    if lock is None:
        return 0
    try:
        return _run()
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
