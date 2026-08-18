"""POST /v1/register — issue a node identity + token, resolve derived location."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, Request

from .auth import new_token, require_internal
from .models import LocTier, RegisterRequest, RegisterResponse
from .privacy import resolve_location

router = APIRouter()


@router.post("/v1/register", response_model=RegisterResponse, status_code=201)
def register(
    body: RegisterRequest,
    request: Request,
    x_gw_internal: str | None = Header(default=None),
) -> RegisterResponse:
    if body.loc_tier == LocTier.region and not body.region:
        raise HTTPException(400, detail="region required for loc_tier=region")
    if body.loc_tier == LocTier.data_share and not body.postcode:
        raise HTTPException(400, detail="postcode required for loc_tier=data_share")

    # Account-linked provisioning is a privileged action: only the trusted portal (holding the
    # internal credential) may attach a node to an account. The public/HA path leaves contributor_ref
    # null and is unaffected.
    if body.contributor_ref is not None:
        require_internal(request, x_gw_internal)

    settings = request.app.state.settings
    client_ip = request.client.host if request.client else None
    loc = resolve_location(
        loc_tier=body.loc_tier.value,
        postcode=body.postcode,
        region=body.region,
        client_ip=client_ip,
        geoip_mmdb=getattr(request.app.state, "geoip", None),
    )

    node_id = uuid.uuid4().hex
    token, token_hash = new_token()

    request.app.state.db.create_node(
        node_id=node_id,
        token_sha256=token_hash,
        device_type=body.device_type,
        firmware=body.firmware,
        cadence_ms=body.cadence_ms,
        loc_tier=body.loc_tier.value,
        loc_ref=loc["loc_ref"],
        cell_id=loc["cell_id"],
        channels=body.channels,
        postcode=loc["stored_postcode"],   # private DB only
        raw_region=loc["raw_region"],      # private DB only
        producer=body.producer,
        contributor_ref=body.contributor_ref,  # private DB only; account link
    )

    return RegisterResponse(
        node_id=node_id, token=token, loc_ref=loc["loc_ref"], cell_id=loc["cell_id"]
    )
