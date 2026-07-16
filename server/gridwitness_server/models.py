"""Request/response schemas and the channel/consent model.

The channel catalogue here is the machine-readable form of the "earn the ask" matrix: which channels
exist, which are electrical vs weather, and which are high-sensitivity. Consent is a *set of channel
names*; the server rejects any row that carries a value for a channel the node did not consent to.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- Channel catalogue ----------------------------------------------------------------------------

# Electrical channels (values live on ElectricalRow).
ELECTRICAL_CHANNELS: frozenset[str] = frozenset(
    {"frequency_hz", "voltage_v", "current_a", "power_w", "power_factor", "phase_angle_deg"}
)
# Weather channels (values live on WeatherRow).
WEATHER_CHANNELS: frozenset[str] = frozenset(
    {"temp", "rhum", "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv"}
)
ALL_CHANNELS: frozenset[str] = ELECTRICAL_CHANNELS | WEATHER_CHANNELS

# Household-sensitive channels — the ones that reveal load/behaviour. Used for extra logging/guards.
HIGH_SENSITIVITY_CHANNELS: frozenset[str] = frozenset({"current_a", "power_w", "power_factor"})


class LocTier(str, Enum):
    anon = "anon"
    region = "region"
    data_share = "data_share"


TsSource = Literal["device", "ha_receive", "gps"]
Phase = Literal["L1", "L2", "L3", "1p"]


# --- Sample rows ----------------------------------------------------------------------------------

class ElectricalRow(BaseModel):
    ts_utc: str
    ts_source: TsSource = "ha_receive"
    phase: Phase = "1p"
    voltage_v: float | None = None
    current_a: float | None = None
    power_w: float | None = None
    power_factor: float | None = None
    frequency_hz: float | None = None
    phase_angle_deg: float | None = None

    def present_channels(self) -> set[str]:
        """Electrical channel names that carry a non-null value on this row."""
        return {c for c in ELECTRICAL_CHANNELS if getattr(self, c) is not None}

    @field_validator("frequency_hz")
    @classmethod
    def _sane_freq(cls, v: float | None) -> float | None:
        if v is not None and not (40.0 <= v <= 70.0):
            raise ValueError(f"frequency_hz {v} outside plausible 40-70 Hz")
        return v


class WeatherRow(BaseModel):
    time: str
    ts_source: Literal["device", "ha_receive"] = "ha_receive"
    temp: float | None = None
    rhum: float | None = None
    wspd: float | None = None
    wdir: float | None = None
    pres: float | None = None
    prcp: float | None = None
    solar_radiation_w_m2: float | None = None
    uv: float | None = None

    def present_channels(self) -> set[str]:
        return {c for c in WEATHER_CHANNELS if getattr(self, c) is not None}


# --- Endpoint bodies ------------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["frequency_hz"])
    loc_tier: LocTier = LocTier.anon
    region: str | None = None       # required iff loc_tier == region
    postcode: str | None = None     # required iff loc_tier == data_share; never staged
    device_type: str = "unknown"
    firmware: str | None = None
    cadence_ms: int | None = None

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ALL_CHANNELS
        if unknown:
            raise ValueError(f"unknown channels: {sorted(unknown)}")
        return v


class RegisterResponse(BaseModel):
    node_id: str
    token: str
    loc_ref: str | None
    cell_id: str | None


class SamplesRequest(BaseModel):
    node_id: str
    client_send_ts: str | None = None
    electrical: list[ElectricalRow] = Field(default_factory=list)
    weather: list[WeatherRow] = Field(default_factory=list)


class RejectedRow(BaseModel):
    index: int
    kind: Literal["electrical", "weather"]
    reason: str


class SamplesResponse(BaseModel):
    server_receive_ts: str
    accepted: int
    duplicates: int
    rejected: list[RejectedRow] = Field(default_factory=list)


class ConsentUpdate(BaseModel):
    node_id: str
    channels: list[str] | None = None
    loc_tier: LocTier | None = None
    region: str | None = None
    postcode: str | None = None

    @field_validator("channels")
    @classmethod
    def _known(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            unknown = set(v) - ALL_CHANNELS
            if unknown:
                raise ValueError(f"unknown channels: {sorted(unknown)}")
        return v


class DeleteRequest(BaseModel):
    node_id: str


class TimeEchoRequest(BaseModel):
    client_send: str


class TimeEchoResponse(BaseModel):
    client_send: str
    server_receive: str
