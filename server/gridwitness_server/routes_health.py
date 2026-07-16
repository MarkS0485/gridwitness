"""GET /v1/health — unauthenticated liveness/readiness."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/health")
def health(request: Request) -> dict:
    db_ok = request.app.state.db.ok()
    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "staging_lag_s": request.app.state.staging.staging_lag_s(),
        "version": request.app.state.settings.version,
    }
