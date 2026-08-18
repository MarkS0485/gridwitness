"""GET /v1/account/export — data portability: hand a contributor a copy of everything of theirs.

"Take your data with you." For the calling account we bundle, per owned survey node:

    * the original files they uploaded (survey_ingest leaves them under archive/ after parsing,
      or they are still in inbox/ if not yet processed);
    * the extracted frequency + voltage series the worker wrote alongside them (extracted_*.csv);
    * a manifest describing each survey.

This is NON-destructive — exporting is not withdrawing. It also stays dependency-light: everything
is read straight from the surveys tree on disk, so the FastAPI tier never needs pandas or the lake.

Internal surface (require_internal): only the trusted portal calls it, scoped to one contributor_ref.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])

_README = """GridWitness — your data export
================================

This archive contains the power-quality survey data associated with your account.

For each survey you uploaded there is a folder named by its node id, containing:
  * the original file(s) you uploaded, exactly as received;
  * extracted_*.csv — the frequency and voltage readings we derived from them and use in the
    research lake (this is the only data taken from your files; nothing else was kept).
  * manifest.json — a description of the survey.

This is your data. We never sell it. You can withdraw any survey at any time from your dashboard;
withdrawing removes it from our systems and drops it from the research lake on the next cycle.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.get("/v1/account/export")
def account_export(request: Request, contributor_ref: str) -> StreamingResponse:
    settings = request.app.state.settings
    nodes = request.app.state.db.get_nodes_by_contributor(contributor_ref)

    buf = io.BytesIO()
    summary: list[dict] = []
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", _README)

        for node in nodes:
            node_id = node["node_id"]
            file_count = 0
            # A survey's files live in archive/ once processed, or inbox/ while still queued. Include
            # both so the export is complete regardless of processing state.
            for area in (settings.surveys_archive, settings.surveys_inbox):
                src = area / node_id
                if not src.is_dir():
                    continue
                for path in sorted(src.rglob("*")):
                    if path.is_file():
                        arcname = f"{node_id}/{path.relative_to(src).as_posix()}"
                        zf.write(path, arcname)
                        file_count += 1
            summary.append({
                "node_id": node_id,
                "device_type": node.get("device_type"),
                "loc_ref": node.get("loc_ref"),
                "channels": node.get("channels"),
                "created_utc": node.get("created_utc"),
                "files_included": file_count,
            })

        zf.writestr("manifest.json", json.dumps({
            "contributor_ref": contributor_ref,
            "exported_utc": _now_iso(),
            "surveys": summary,
        }, indent=2))

    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="my-gridwitness-data.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)
