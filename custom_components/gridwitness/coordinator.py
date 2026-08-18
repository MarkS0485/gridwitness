"""Capture + push coordinator.

Capture is event-driven (``async_track_state_change_event``); a periodic timer
(``async_track_time_interval``, every PUSH_INTERVAL_S) flushes the batch to the ingest server and, on
failure, spills to the disk buffer and drains it on reconnect. This is deliberately NOT a
DataUpdateCoordinator — nothing is polled; we emit what the meters report.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from . import ntp
from .api_client import ApiClient, GridWitnessApiError
from .buffer import DiskBuffer
from .const import (
    ELECTRICAL_CHANNELS,
    NTP_MAX_PLAUSIBLE_S,
    NTP_SERVERS,
    NTP_SYNC_INTERVAL_H,
    PUSH_INTERVAL_S,
    WEATHER_CHANNELS,
)

_LOGGER = logging.getLogger(__name__)
_DRAIN_CHUNK = 2000
_UNAVAILABLE = {"unknown", "unavailable", "none", "", None}


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_util.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class GridWitnessCoordinator:
    def __init__(
        self,
        hass: HomeAssistant,
        api: ApiClient,
        buffer: DiskBuffer,
        *,
        node_id: str,
        token: str,
        mapping: dict[str, list[dict[str, str]]],
    ) -> None:
        self.hass = hass
        self.api = api
        self.buffer = buffer
        self.node_id = node_id
        self.token = token
        # reverse index: entity_id -> list of (channel, phase)
        self._index: dict[str, list[tuple[str, str]]] = {}
        for channel, entries in mapping.items():
            for e in entries:
                self._index.setdefault(e["entity_id"], []).append((channel, e.get("phase", "1p")))

        self._pending: list[tuple[str, dict]] = []
        self._unsubs: list = []
        self._listeners: list = []

        # --- public stats for the give-back sensors ---
        self.online: bool = True
        self.clock_offset_ms: float | None = None       # transport (server round-trip) offset
        self.ntp_offset_ms: float | None = None          # authoritative node-clock offset (multi-NTP)
        self._ntp_offset_s: float = 0.0                  # applied to ha_receive stamps
        self.last_frequency_hz: float | None = None
        self.samples_total: int = 0
        self.samples_today: int = 0
        self._today: str = dt_util.utcnow().date().isoformat()

    # --- lifecycle --------------------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        entity_ids = list(self._index)
        if entity_ids:
            self._unsubs.append(
                async_track_state_change_event(self.hass, entity_ids, self._on_state_event)
            )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_flush, timedelta(seconds=PUSH_INTERVAL_S))
        )
        # authoritative clock: sync now, then every NTP_SYNC_INTERVAL_H hours
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._refresh_ntp, timedelta(hours=NTP_SYNC_INTERVAL_H)
            )
        )
        self.hass.async_create_task(self._refresh_ntp(None))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # best-effort final spill so nothing in memory is lost on unload
        if self._pending:
            await self._append_buffer(self._pending)
            self._pending.clear()

    @callback
    def async_add_listener(self, update_cb) -> callback:
        self._listeners.append(update_cb)

        def _remove() -> None:
            if update_cb in self._listeners:
                self._listeners.remove(update_cb)

        return _remove

    @callback
    def _notify(self) -> None:
        self._roll_day()
        for cb in list(self._listeners):
            cb()

    # --- capture ----------------------------------------------------------------------------------

    @callback
    def _on_state_event(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        raw = new_state.state
        if raw in _UNAVAILABLE:
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return

        # Stamp with the NTP-corrected host clock (authoritative). When device/GPS source stamps are
        # added later they are already true time and must NOT be offset — only ha_receive is corrected.
        stamped = new_state.last_updated + timedelta(seconds=self._ntp_offset_s)
        ts, ts_source = _iso(stamped), "ha_receive"
        for channel, phase in self._index.get(new_state.entity_id, []):
            if channel in ELECTRICAL_CHANNELS:
                self._pending.append(
                    ("electrical", {"ts_utc": ts, "ts_source": ts_source, "phase": phase, channel: value})
                )
                if channel == "frequency_hz":
                    self.last_frequency_hz = value
            elif channel in WEATHER_CHANNELS:
                self._pending.append(
                    ("weather", {"time": ts, "ts_source": ts_source, channel: value})
                )

    # --- flush / push -----------------------------------------------------------------------------

    async def _on_flush(self, _now) -> None:
        batch = self._pending
        self._pending = []
        try:
            drained = await self._drain_disk()
            if not drained:
                if batch:
                    await self._append_buffer(batch)
                self._set_online(False)
                return
            if batch:
                try:
                    await self._push_items(batch)
                    self._set_online(True)
                except GridWitnessApiError as err:
                    if err.retryable:
                        await self._append_buffer(batch)
                        self._set_online(False)
                    else:
                        _LOGGER.warning("Dropping %d rows on non-retryable error: %s", len(batch), err)
            await self._update_offset()
        finally:
            self._notify()

    async def _drain_disk(self) -> bool:
        """Push buffered backlog oldest-first. Returns False if the server is unreachable."""
        while True:
            chunk = await self.hass.async_add_executor_job(self.buffer.peek, _DRAIN_CHUNK)
            if not chunk:
                return True
            try:
                await self._push_items(chunk)
            except GridWitnessApiError as err:
                if err.retryable:
                    return False
                _LOGGER.warning("Dropping %d buffered rows (non-retryable): %s", len(chunk), err)
            await self.hass.async_add_executor_job(self.buffer.commit, len(chunk))

    async def _push_items(self, items: list[tuple[str, dict]]) -> None:
        electrical = [row for kind, row in items if kind == "electrical"]
        weather = [row for kind, row in items if kind == "weather"]
        resp = await self.api.post_samples(
            self.node_id, self.token, electrical=electrical, weather=weather
        )
        accepted = int(resp.get("accepted", 0))
        self.samples_total += accepted
        self.samples_today += accepted

    async def _append_buffer(self, items: list[tuple[str, dict]]) -> None:
        now = _iso(dt_util.utcnow())
        await self.hass.async_add_executor_job(self.buffer.append, items, now)
        await self.hass.async_add_executor_job(self.buffer.prune, dt_util.utcnow())

    async def _refresh_ntp(self, _now) -> None:
        """Re-derive the authoritative node clock offset from multiple NTP servers (median)."""
        offset_s = await self.hass.async_add_executor_job(
            ntp.authoritative_offset, NTP_SERVERS
        )
        if offset_s is None:
            _LOGGER.debug("NTP sync: no usable responses; keeping offset %.1f ms",
                          (self.ntp_offset_ms or 0.0))
            return
        if abs(offset_s) > NTP_MAX_PLAUSIBLE_S:
            _LOGGER.warning("NTP offset %.3fs implausibly large; ignoring", offset_s)
            return
        self._ntp_offset_s = offset_s
        self.ntp_offset_ms = round(offset_s * 1000.0, 1)
        _LOGGER.debug("NTP sync: node clock offset %.1f ms", self.ntp_offset_ms)
        self._notify()

    async def _update_offset(self) -> None:
        """NTP-style transport offset from a time-echo round trip."""
        t0 = dt_util.utcnow()
        try:
            resp = await self.api.time_echo()
        except GridWitnessApiError:
            return
        t1 = dt_util.utcnow()
        try:
            server = dt_util.parse_datetime(resp["server_receive"])
        except (KeyError, ValueError):
            return
        if server is None:
            return
        midpoint = t0 + (t1 - t0) / 2
        self.clock_offset_ms = round((server - midpoint).total_seconds() * 1000.0, 1)

    # --- stats helpers ----------------------------------------------------------------------------

    @property
    def buffer_backlog(self) -> int:
        return self.buffer.count()

    def _set_online(self, online: bool) -> None:
        self.online = online

    def _roll_day(self) -> None:
        today = dt_util.utcnow().date().isoformat()
        if today != self._today:
            self._today = today
            self.samples_today = 0
