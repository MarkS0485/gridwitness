"""Internal admin API — the account portal manages a contributor's nodes on their behalf.

    GET    /v1/admin/nodes?contributor_ref=   list the account's live nodes
    PATCH  /v1/admin/node/{node_id}           alter consent / location for an owned node
    DELETE /v1/admin/node/{node_id}           GDPR erasure of an owned node (tombstone downstream)

Every route requires the internal credential (``require_internal``) — this surface is never exposed
to the public internet; the portal calls it over the private container network. Ownership is enforced
on every mutating call: the ``contributor_ref`` presented must match the one stored against the node,
or the node is treated as not found (so the portal cannot touch another account's data).
"""
from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import require_internal
from .models import AdminConsentUpdate, AdminNodeView, LocTier
from .privacy import resolve_location

router = APIRouter(dependencies=[Depends(require_internal)])


def _owned_node(request: Request, node_id: str, contributor_ref: str) -> dict:
    """Return the live node iff it exists and is owned by ``contributor_ref``, else 404."""
    db = request.app.state.db
    node = db.get_node(node_id)
    if node is None or db.get_contributor_ref(node_id) != contributor_ref:
        raise HTTPException(status_code=404, detail="unknown node")
    return node


@router.get("/v1/admin/nodes", response_model=list[AdminNodeView])
def list_nodes(request: Request, contributor_ref: str) -> list[AdminNodeView]:
    rows = request.app.state.db.get_nodes_by_contributor(contributor_ref)
    return [AdminNodeView(**row) for row in rows]


@router.patch("/v1/admin/node/{node_id}")
def update_node(
    node_id: str, contributor_ref: str, body: AdminConsentUpdate, request: Request
) -> dict:
    node = _owned_node(request, node_id, contributor_ref)
    loc_ref = node["loc_ref"]
    cell_id = node["cell_id"]
    stored_postcode = None
    if body.loc_tier is not None:
        if body.loc_tier == LocTier.region and not body.region:
            raise HTTPException(400, detail="region required for loc_tier=region")
        if body.loc_tier == LocTier.data_share and not body.postcode:
            raise HTTPException(400, detail="postcode required for loc_tier=data_share")
        loc = resolve_location(
            loc_tier=body.loc_tier.value,
            postcode=body.postcode,
            region=body.region,
            client_ip=None,  # the portal is the caller; anon geo-IP is meaningless here
            geoip_mmdb=getattr(request.app.state, "geoip", None),
        )
        loc_ref, cell_id, stored_postcode = loc["loc_ref"], loc["cell_id"], loc["stored_postcode"]

    request.app.state.db.update_consent(
        node_id,
        channels=body.channels,
        loc_tier=body.loc_tier.value if body.loc_tier else None,
        loc_ref=loc_ref,
        cell_id=cell_id,
        postcode=stored_postcode,
    )
    return {"node_id": node_id, "loc_ref": loc_ref}


@router.delete("/v1/admin/node/{node_id}")
def delete_node(node_id: str, contributor_ref: str, request: Request) -> dict:
    _owned_node(request, node_id, contributor_ref)
    deleted = request.app.state.db.delete_node(node_id)
    if deleted:
        # Withdrawal removes the raw contribution now: purge any survey files (queued in inbox or
        # already parsed into archive). The tombstone drops the derived rows from the lake on the
        # next acquisition cycle. Analysis already built while the data was live can't be un-made.
        settings = request.app.state.settings
        for d in (settings.surveys_inbox / node_id, settings.surveys_archive / node_id):
            shutil.rmtree(d, ignore_errors=True)
    return {"node_id": node_id, "deleted": deleted, "tombstoned": deleted}
