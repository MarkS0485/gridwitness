"""Sample ingestion + node consent/erasure.

    POST   /v1/samples   push a batch (auth, rate-limit, consent-enforce, dedupe, stage)
    PATCH  /v1/node      change/revoke consent
    DELETE /v1/node      GDPR erasure (tombstone honoured downstream)

Consent enforcement is the load-bearing rule: a row carrying a value for a channel the node did not
consent to is REJECTED, not silently dropped or accepted. The server is the enforcement point, so a
buggy or hostile client cannot over-share.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import authenticate_node, require_bearer
from .models import (
    ConsentUpdate,
    DeleteRequest,
    LocTier,
    RejectedRow,
    SamplesRequest,
    SamplesResponse,
)
from .privacy import project_electrical, project_weather, resolve_location

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.post("/v1/samples", response_model=SamplesResponse, dependencies=[Depends(require_bearer)])
def post_samples(body: SamplesRequest, request: Request) -> SamplesResponse:
    node = authenticate_node(request, body.node_id)
    consented: set[str] = node["channels"]

    total_rows = len(body.electrical) + len(body.weather)
    if not request.app.state.limiter.allow(body.node_id, max(total_rows, 1)):
        raise HTTPException(429, detail="rate limit exceeded")

    rejected: list[RejectedRow] = []
    elec_ok: list[dict] = []
    for i, row in enumerate(body.electrical):
        unconsented = row.present_channels() - consented
        if unconsented:
            rejected.append(RejectedRow(
                index=i, kind="electrical",
                reason=f"channel(s) not consented: {sorted(unconsented)}",
            ))
            continue
        elec_ok.append(project_electrical(row, node))

    weather_ok: list[dict] = []
    for i, row in enumerate(body.weather):
        unconsented = row.present_channels() - consented
        if unconsented:
            rejected.append(RejectedRow(
                index=i, kind="weather",
                reason=f"channel(s) not consented: {sorted(unconsented)}",
            ))
            continue
        weather_ok.append(project_weather(row, node))

    staging = request.app.state.staging
    e_acc, e_dup = staging.write_electrical(elec_ok)
    w_acc, w_dup = staging.write_weather(weather_ok)

    return SamplesResponse(
        server_receive_ts=_now_iso(),
        accepted=e_acc + w_acc,
        duplicates=e_dup + w_dup,
        rejected=rejected,
    )


@router.patch("/v1/node", dependencies=[Depends(require_bearer)])
def update_node(body: ConsentUpdate, request: Request) -> dict:
    node = authenticate_node(request, body.node_id)
    loc_ref = node["loc_ref"]
    cell_id = node["cell_id"]
    stored_postcode = None
    if body.loc_tier is not None:
        if body.loc_tier == LocTier.region and not body.region:
            raise HTTPException(400, detail="region required for loc_tier=region")
        if body.loc_tier == LocTier.data_share and not body.postcode:
            raise HTTPException(400, detail="postcode required for loc_tier=data_share")
        client_ip = request.client.host if request.client else None
        loc = resolve_location(
            loc_tier=body.loc_tier.value,
            postcode=body.postcode,
            region=body.region,
            client_ip=client_ip,
            geoip_mmdb=getattr(request.app.state, "geoip", None),
        )
        loc_ref, cell_id, stored_postcode = loc["loc_ref"], loc["cell_id"], loc["stored_postcode"]

    request.app.state.db.update_consent(
        body.node_id,
        channels=body.channels,
        loc_tier=body.loc_tier.value if body.loc_tier else None,
        loc_ref=loc_ref,
        cell_id=cell_id,
        postcode=stored_postcode,
    )
    return {"loc_ref": loc_ref}


@router.delete("/v1/node", dependencies=[Depends(require_bearer)])
def delete_node(body: DeleteRequest, request: Request) -> dict:
    authenticate_node(request, body.node_id)
    deleted = request.app.state.db.delete_node(body.node_id)
    return {"deleted": deleted, "tombstoned": deleted}
