"""Request/response schemas and the channel/consent model.

The channel catalogue here is the machine-readable form of the "earn the ask" matrix: which channels
exist, which are electrical vs weather, and which are high-sensitivity. Consent is a *set of channel
names*; the server rejects any row that carries a value for a channel the node did not consent to.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- Channel catalogue (single source of truth for the published schema) ---------------------------
#
# One authoritative list of every channel a submitter may send: its kind (which row it lives on),
# unit, JSON type, sensitivity, and a one-line meaning. The frozensets below are derived from this,
# and the schema exporter publishes it as schema/channels.v1.json so third parties can code to it.
SCHEMA_VERSION = "1.0"

CHANNEL_CATALOGUE: dict[str, dict[str, str]] = {
    # electrical
    "frequency_hz": {"kind": "electrical", "unit": "Hz", "type": "number", "sensitivity": "none",
                     "description": "System frequency, node-global (~49-51 Hz on GB)."},
    "voltage_v": {"kind": "electrical", "unit": "V", "type": "number", "sensitivity": "low",
                  "description": "RMS voltage. A property of your local feeder, not you."},
    "current_a": {"kind": "electrical", "unit": "A", "type": "number", "sensitivity": "high",
                  "description": "RMS current. Reveals household load; opt-in only."},
    "power_w": {"kind": "electrical", "unit": "W", "type": "number", "sensitivity": "high",
                "description": "Real power. Reveals household load; opt-in only."},
    "power_factor": {"kind": "electrical", "unit": "", "type": "number", "sensitivity": "high",
                     "description": "Power factor (-1..1). Reveals load character; opt-in only."},
    "phase_angle_deg": {"kind": "electrical", "unit": "deg", "type": "number", "sensitivity": "low",
                        "description": "Synchrophasor angle vs UTC (GPS/PMU nodes only)."},
    # weather (Meteostat-shaped so it joins the GDA weather cell grid downstream)
    "temp": {"kind": "weather", "unit": "degC", "type": "number", "sensitivity": "low",
             "description": "Ambient outdoor temperature."},
    "rhum": {"kind": "weather", "unit": "%", "type": "number", "sensitivity": "low",
             "description": "Relative humidity."},
    "wspd": {"kind": "weather", "unit": "km/h", "type": "number", "sensitivity": "low",
             "description": "Wind speed (note measurement height)."},
    "wdir": {"kind": "weather", "unit": "deg", "type": "number", "sensitivity": "low",
             "description": "Wind direction, meteorological 'from' (0=N, 90=E)."},
    "pres": {"kind": "weather", "unit": "hPa", "type": "number", "sensitivity": "low",
             "description": "Atmospheric pressure."},
    "prcp": {"kind": "weather", "unit": "mm", "type": "number", "sensitivity": "low",
             "description": "Rainfall."},
    "solar_radiation_w_m2": {"kind": "weather", "unit": "W/m2", "type": "number", "sensitivity": "low",
                             "description": "Shortwave irradiance."},
    "uv": {"kind": "weather", "unit": "index", "type": "number", "sensitivity": "low",
           "description": "UV index."},
}

ELECTRICAL_CHANNELS: frozenset[str] = frozenset(
    k for k, v in CHANNEL_CATALOGUE.items() if v["kind"] == "electrical"
)
WEATHER_CHANNELS: frozenset[str] = frozenset(
    k for k, v in CHANNEL_CATALOGUE.items() if v["kind"] == "weather"
)
ALL_CHANNELS: frozenset[str] = ELECTRICAL_CHANNELS | WEATHER_CHANNELS

# Household-sensitive channels — the ones that reveal load/behaviour. Used for extra logging/guards.
HIGH_SENSITIVITY_CHANNELS: frozenset[str] = frozenset(
    k for k, v in CHANNEL_CATALOGUE.items() if v["sensitivity"] == "high"
)

# Power-quality survey ingestion (electricians' logger exports). A survey is an ordinary node tagged
# with this producer, consenting only to the two safe electrical channels: frequency (node-global,
# reveals nothing) and voltage (a property of the local feeder, not the occupant). The survey_ingest
# worker extracts ONLY these from uploaded files — everything else in a file is dropped at source.
SURVEY_PRODUCER = "gridwitness-survey"
SURVEY_CHANNELS: list[str] = ["frequency_hz", "voltage_v"]


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
    # Who is submitting: the client software name/version, e.g. "gridwitness-ha/0.1.0" or
    # "acme-energy-app/2.3". Third-party submitters should set this; stored server-side for provenance.
    producer: str | None = None
    # Account link. Set only by the trusted portal (requires the internal credential); ties this node
    # to a confirmed-able account so ownership is provable and GDPR erasure can be honoured. The public
    # HA path leaves this null and registration stays open as before.
    contributor_ref: str | None = None
    schema_version: str = SCHEMA_VERSION

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
    schema_version: str = SCHEMA_VERSION
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


# --- Internal admin API (account portal only) -----------------------------------------------------

class AdminNodeView(BaseModel):
    """A node as shown to its owning account in the portal dashboard. No token, no private location."""
    node_id: str
    device_type: str | None = None
    firmware: str | None = None
    cadence_ms: int | None = None
    loc_tier: str
    loc_ref: str | None = None
    cell_id: str | None = None
    channels: list[str] = Field(default_factory=list)
    producer: str | None = None
    created_utc: str


class AdminConsentUpdate(BaseModel):
    """Portal-side consent/location change for one owned node. node_id + owner come from the route."""
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


class TimeEchoRequest(BaseModel):
    client_send: str


class TimeEchoResponse(BaseModel):
    client_send: str
    server_receive: str
