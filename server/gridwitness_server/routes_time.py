"""POST /v1/time-echo — lightweight NTP-style offset probe (no data, no auth)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from .models import TimeEchoRequest, TimeEchoResponse

router = APIRouter()


@router.post("/v1/time-echo", response_model=TimeEchoResponse)
def time_echo(body: TimeEchoRequest) -> TimeEchoResponse:
    server_receive = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return TimeEchoResponse(client_send=body.client_send, server_receive=server_receive)
