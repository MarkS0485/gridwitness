"""Async HTTP client to the GridWitness ingest server.

Thin wrapper over Home Assistant's shared aiohttp session (no bundled HTTP dependency). Codes to the
contract in docs/ingest-api.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiohttp


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class GridWitnessApiError(Exception):
    """Raised on a non-success response. ``status`` is the HTTP code (or None for transport error)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        # 5xx / 429 / transport errors are worth buffering-and-retrying; 4xx (except 429) are not.
        return self.status is None or self.status == 429 or self.status >= 500


class ApiClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, *, allow_insecure: bool = False):
        self._session = session
        self._base = base_url.rstrip("/")
        # ssl=False disables verification for self-signed certs / plain-http LAN testing only.
        self._ssl = False if allow_insecure else None

    async def _request(self, method: str, path: str, *, token: str | None = None,
                       json: dict | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with self._session.request(
                method, f"{self._base}{path}", json=json, headers=headers, ssl=self._ssl,
            ) as resp:
                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    detail = (body or {}).get("detail") if isinstance(body, dict) else None
                    raise GridWitnessApiError(f"{path} -> {resp.status}: {detail}", status=resp.status)
                return body or {}
        except aiohttp.ClientError as err:
            raise GridWitnessApiError(f"{path} transport error: {err}", status=None) from err

    async def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/register", json=payload)

    async def post_samples(self, node_id: str, token: str, *,
                           electrical: list[dict], weather: list[dict]) -> dict[str, Any]:
        body = {
            "node_id": node_id,
            "client_send_ts": _now_iso(),
            "electrical": electrical,
            "weather": weather,
        }
        return await self._request("POST", "/v1/samples", token=token, json=body)

    async def time_echo(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/time-echo", json={"client_send": _now_iso()})

    async def update_consent(self, node_id: str, token: str, update: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", "/v1/node", token=token, json={"node_id": node_id, **update})

    async def delete_node(self, node_id: str, token: str) -> dict[str, Any]:
        return await self._request("DELETE", "/v1/node", token=token, json={"node_id": node_id})

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/health")
