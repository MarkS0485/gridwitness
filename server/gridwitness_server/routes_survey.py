"""POST /v1/survey/upload — accept power-quality survey files from the account portal.

A "survey" is one monitoring session an electrician uploads (a site, a few days): up to 100 files
exported from a power-quality analyser. This endpoint is deliberately FAST and does NO parsing:

    1. register an ordinary node for the survey (producer=gridwitness-survey), consenting only to
       frequency + voltage, owned by the caller's contributor_ref;
    2. stash the raw files under staging/surveys/inbox/<node_id>/ with a manifest;
    3. return immediately.

The heavy work (parse each file, keep only frequency + voltage, project through the privacy
allow-list, stage, then archive the raw originals) is done out-of-band by the survey_ingest worker,
mirroring the GDA acquirer pattern. Nothing here touches pandas or the lake.

Internal surface: the whole router requires the internal credential — only the trusted portal, which
holds contributor ownership, may call it. It is never exposed to the public internet.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from .auth import new_token, require_internal
from .models import SURVEY_CHANNELS, SURVEY_PRODUCER, LocTier
from .privacy import resolve_location

router = APIRouter(dependencies=[Depends(require_internal)])

# Formats the survey_ingest worker knows how to read. CSV/text from any analyser, plus PQDIF binary.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".txt", ".tsv", ".pqd", ".pqdif"})
MAX_FILES = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_name(raw: str | None, index: int) -> str:
    """A collision- and traversal-safe on-disk name that keeps the original for the contributor.

    We strip any directory component (``Path(...).name``) so a crafted filename can't escape the
    node's inbox, and prefix an index so two files with the same basename don't clobber each other.
    """
    base = Path(raw or "").name.strip() or f"file{index}"
    return f"{index:03d}_{base}"


@router.post("/v1/survey/upload")
async def survey_upload(
    request: Request,
    contributor_ref: str = Form(...),
    label: str = Form(...),
    loc_tier: str = Form("region"),
    region: str | None = Form(None),
    postcode: str | None = Form(None),
    device_type: str = Form("unknown"),
    notes: str | None = Form(None),
    files: list[UploadFile] = File(...),
) -> dict:
    # --- Validate the batch --------------------------------------------------------------------
    if not files:
        raise HTTPException(400, detail="no files uploaded")
    if len(files) > MAX_FILES:
        raise HTTPException(400, detail=f"too many files: {len(files)} (max {MAX_FILES})")

    # Surveys must carry a location: a voltage trace is only research-useful pinned to a place, and
    # frequency alone is grid-global. Anonymous is therefore refused for the survey path (unlike the
    # default HA path). Location is still coarse-only — postcode is kept private, never staged.
    if loc_tier not in (LocTier.region.value, LocTier.data_share.value):
        raise HTTPException(400, detail="surveys require loc_tier 'region' or 'data_share'")
    if loc_tier == LocTier.region.value and not region:
        raise HTTPException(400, detail="region required for loc_tier=region")
    if loc_tier == LocTier.data_share.value and not postcode:
        raise HTTPException(400, detail="postcode required for loc_tier=data_share")

    # Sort accepted vs rejected files by extension before we provision anything.
    accepted_files: list[UploadFile] = []
    rejected: list[dict] = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext in ALLOWED_EXTENSIONS:
            accepted_files.append(f)
        else:
            rejected.append({"filename": f.filename, "reason": f"unsupported extension '{ext}'"})
    if not accepted_files:
        raise HTTPException(400, detail="no files with a supported extension (.csv/.txt/.pqd/.pqdif)")

    # --- Register the survey node (reuses the standard node provisioning path) ------------------
    loc = resolve_location(
        loc_tier=loc_tier,
        postcode=postcode,
        region=region,
        client_ip=None,  # the portal is the caller; anon geo-IP is meaningless here
        geoip_mmdb=getattr(request.app.state, "geoip", None),
    )

    node_id = uuid.uuid4().hex
    _token, token_hash = new_token()  # a token is minted for schema symmetry; the survey path is file-based
    request.app.state.db.create_node(
        node_id=node_id,
        token_sha256=token_hash,
        device_type=(device_type or "unknown").strip(),
        firmware=None,
        cadence_ms=None,
        loc_tier=loc_tier,
        loc_ref=loc["loc_ref"],
        cell_id=loc["cell_id"],
        channels=list(SURVEY_CHANNELS),
        postcode=loc["stored_postcode"],   # private DB only, never staged
        raw_region=loc["raw_region"],      # private DB only
        producer=SURVEY_PRODUCER,
        contributor_ref=contributor_ref,   # private DB only; account link for ownership + erasure
    )

    # --- Stash the raw files + a manifest under the node's inbox --------------------------------
    inbox = request.app.state.settings.surveys_inbox / node_id
    inbox.mkdir(parents=True, exist_ok=True)

    stored: list[dict] = []
    for i, f in enumerate(accepted_files):
        name = _safe_name(f.filename, i)
        dest = inbox / name
        size = 0
        with dest.open("wb") as out:
            while chunk := await f.read(1 << 20):  # 1 MiB chunks, never buffer a whole file
                out.write(chunk)
                size += len(chunk)
        await f.close()
        stored.append({"stored_name": name, "original_name": f.filename, "bytes": size})

    # Manifest is deliberately PII-free: no postcode (that lives only in the private DB). It carries
    # the coarse label/region so the worker and the export bundle can describe the survey.
    manifest = {
        "node_id": node_id,
        "contributor_ref": contributor_ref,
        "label": label.strip(),
        "device_type": (device_type or "unknown").strip(),
        "notes": (notes or "").strip() or None,
        "loc_tier": loc_tier,
        "region": region,
        "loc_ref": loc["loc_ref"],
        "uploaded_utc": _now_iso(),
        "status": "queued",
        "files": stored,
    }
    (inbox / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "survey_id": node_id,
        "node_id": node_id,
        "loc_ref": loc["loc_ref"],
        "accepted": len(stored),
        "rejected": rejected,
    }
