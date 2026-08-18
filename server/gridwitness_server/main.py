"""FastAPI app assembly + entrypoint.

    create_app()  -> a configured FastAPI instance (used by tests and by run())
    run()         -> uvicorn launcher for the console script / `python -m gridwitness_server.main`
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Settings, get_settings
from .db import Database
from .ratelimit import RateLimiter
from .routes_account import router as account_router
from .routes_admin import router as admin_router
from .routes_health import router as health_router
from .routes_ingest import router as ingest_router
from .routes_register import router as register_router
from .routes_survey import router as survey_router
from .routes_time import router as time_router
from .staging import StagingWriter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db = Database(settings.db_path)
        app.state.staging = StagingWriter(settings.staging_dir)
        app.state.limiter = RateLimiter(settings.rate_rows_per_min)
        app.state.geoip = None  # wired in P1 if a GeoLite2 db is configured
        try:
            yield
        finally:
            app.state.db.close()

    app = FastAPI(title="GridWitness ingest", version=__version__, lifespan=lifespan)

    # Uniform error envelope: {"error": <code>, "detail": <message>}.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_req: Request, exc: StarletteHTTPException):
        codes = {400: "bad_request", 401: "unauthorized", 404: "not_found",
                 409: "conflict", 429: "rate_limited", 503: "backpressure"}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": codes.get(exc.status_code, "error"), "detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_req: Request, exc: RequestValidationError):
        # Reduce to JSON-safe fields — pydantic's raw error ctx can hold non-serializable objects.
        detail = [
            {"type": e.get("type"), "loc": list(e.get("loc", [])), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=400, content={"error": "validation", "detail": detail})

    app.include_router(register_router)
    app.include_router(ingest_router)
    app.include_router(time_router)
    app.include_router(health_router)
    app.include_router(admin_router)
    app.include_router(survey_router)
    app.include_router(account_router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    host = os.environ.get("GW_HOST", "0.0.0.0")
    port = int(os.environ.get("GW_PORT", "8000"))
    uvicorn.run("gridwitness_server.main:app", host=host, port=port, workers=1)


if __name__ == "__main__":
    run()
