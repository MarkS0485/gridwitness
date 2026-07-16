"""Constants and the channel/consent model for the GridWitness integration.

The channel catalogue mirrors the server's (docs/data-model.md) and is the machine form of the
"earn the ask" matrix: what we can collect, grouped into the consent units the user sees.
"""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "gridwitness"

# --- config entry / options keys ------------------------------------------------------------------
CONF_SERVER_URL: Final = "server_url"
CONF_ALLOW_INSECURE: Final = "allow_insecure"     # accept self-signed / http on LAN during testing
CONF_NODE_ID: Final = "node_id"
CONF_TOKEN: Final = "token"                        # stored in the (encrypted) config entry
CONF_CHANNELS: Final = "channels"                  # list[str] of consented channel names
CONF_LOC_TIER: Final = "loc_tier"
CONF_REGION: Final = "region"
CONF_POSTCODE: Final = "postcode"                  # only sent to server; not retained if avoidable
CONF_MAPPING: Final = "mapping"                    # channel -> {entity_id, phase}
CONF_LOC_REF: Final = "loc_ref"                    # server-derived, echoed back for display

DEFAULT_SERVER_URL: Final = "http://localhost:8000"
# Production endpoint once TLS is live (Caddy + Let's Encrypt). Becomes the default at launch.
PROD_SERVER_URL: Final = "https://ingest.twinscrollgridbalancer.co.uk"

# --- push / buffer defaults -----------------------------------------------------------------------
PUSH_INTERVAL_S: Final = 30
MAX_BUFFER_ROWS: Final = 250_000          # cap disk buffer to protect SD-card installs
MAX_BUFFER_AGE_H: Final = 72             # drop buffered rows older than this on drain

# --- NTP clock discipline -------------------------------------------------------------------------
NTP_SERVERS: Final = ("time.cloudflare.com", "time.google.com", "pool.ntp.org", "uk.pool.ntp.org")
NTP_SYNC_INTERVAL_H: Final = 6           # re-query the authoritative offset this often
# Ignore an NTP offset larger than this (s) as implausible — likely a misconfigured host, not drift.
NTP_MAX_PLAUSIBLE_S: Final = 30.0

# --- location tiers -------------------------------------------------------------------------------
LOC_ANON: Final = "anon"
LOC_REGION: Final = "region"
LOC_DATA_SHARE: Final = "data_share"
LOC_TIERS: Final = (LOC_ANON, LOC_REGION, LOC_DATA_SHARE)

# GB DNO / GSP regions offered in REGION tier.
REGIONS: Final = (
    "NORTH_SCOTLAND", "CENTRAL_SCOTLAND", "SOUTH_SCOTLAND", "NORTH_EAST", "NORTH_WEST",
    "MERSEY", "YORKSHIRE", "MIDLANDS", "EAST_MIDLANDS", "EAST_ENGLAND", "LONDON",
    "SOUTH_WALES", "SOUTH_WEST", "SOUTHERN", "SOUTH_EAST",
)

# --- channel catalogue ----------------------------------------------------------------------------
# HA SensorDeviceClass string value -> GridWitness channel name.
DEVICE_CLASS_CHANNELS: Final[dict[str, str]] = {
    "voltage": "voltage_v",
    "current": "current_a",
    "power": "power_w",
    "power_factor": "power_factor",
    "frequency": "frequency_hz",
    "temperature": "temp",
    "humidity": "rhum",
    "wind_speed": "wspd",
    "wind_direction": "wdir",       # not a standard SensorDeviceClass everywhere; may need manual map
    "pressure": "pres",
    "atmospheric_pressure": "pres",
    "precipitation": "prcp",
    "precipitation_intensity": "prcp",
    "irradiance": "solar_radiation_w_m2",
}

ELECTRICAL_CHANNELS: Final = frozenset(
    {"frequency_hz", "voltage_v", "current_a", "power_w", "power_factor", "phase_angle_deg"}
)
WEATHER_CHANNELS: Final = frozenset(
    {"temp", "rhum", "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv"}
)

# Channels that reveal household behaviour — surfaced with the strongest consent copy.
HIGH_SENSITIVITY_CHANNELS: Final = frozenset({"current_a", "power_w", "power_factor"})

# Consent groups the user toggles (a group = the checkbox unit in the consent screen).
# The order is the escalation order; frequency is default-on.
CONSENT_GROUPS: Final = {
    "frequency": {"channels": ["frequency_hz"], "default": True, "sensitivity": "none"},
    "voltage": {"channels": ["voltage_v"], "default": False, "sensitivity": "low"},
    "current_power": {
        "channels": ["current_a", "power_w", "power_factor"],
        "default": False, "sensitivity": "high",
    },
    "weather": {
        "channels": ["temp", "rhum", "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv"],
        "default": False, "sensitivity": "low",
    },
}

# Which HA device_class values feed each consent group (drives discovery grouping / relevance).
GROUP_DEVICE_CLASSES: Final = {
    "frequency": {"frequency"},
    "voltage": {"voltage"},
    "current_power": {"current", "power", "power_factor"},
    "weather": {"temperature", "humidity", "wind_speed", "wind_direction",
                "pressure", "atmospheric_pressure", "precipitation",
                "precipitation_intensity", "irradiance"},
}
