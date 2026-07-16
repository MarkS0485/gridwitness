"""Per-node bearer tokens.

A token is a random 32-byte urlsafe secret returned once at registration. Only its sha256 is stored.
``require_node`` is a FastAPI dependency that authenticates a request and returns the node record.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException, Request

from .db import Database


def new_token() -> tuple[str, str]:
    """Return (plaintext_token, sha256_hex). Only the hash is ever stored."""
    tok = secrets.token_urlsafe(32)
    return tok, sha256(tok)


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_bearer(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Dependency: assert a Bearer token is present and stash its hash for authenticate_node().

    The token alone doesn't name the node — the request body/query does. The route calls
    ``authenticate_node`` once the node_id is known, so a token can only ever act on its own node.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    request.state.presented_token_hash = sha256(token)


def authenticate_node(request: Request, node_id: str) -> dict:
    """Given a node_id from the body/path, verify the presented token matches and return the node."""
    db: Database = request.app.state.db
    node = db.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node")
    stored = db.get_token_hash(node_id)
    presented = getattr(request.state, "presented_token_hash", None)
    if stored is None or presented is None or not hmac.compare_digest(stored, presented):
        raise HTTPException(status_code=401, detail="invalid token for node")
    return node
