"""Privacy boundary: staging projection, cell snapping, and location resolution.

Two responsibilities:

1. **Allow-list projection**. The CSV row is built field-by-field from an explicit list. Request
   objects are NEVER copied wholesale, so postcode, lat-lon, token, and contributor identity are
   *structurally incapable* of reaching a staging file. This is the load-bearing privacy guarantee.

2. **Location resolution**. Turn a postcode (data-share) or source IP (anon) into a *derived* coarse
   key (loc_ref = GSP group or primary substation; cell_id = 0.25 deg grid cell). The raw postcode
   and IP stay in the private DB or are discarded; only the derived keys travel with the data.

The postcode->GSP/lat-lon resolver here is a documented P0 STUB. The real implementation reuses GDA's
``Ingest/weather/postcode_source.json`` + ``geocode_postcodes.py`` and NESO_GIS boundary polygons.
"""
from __future__ import annotations

import math
from typing import Any

from .models import ElectricalRow, WeatherRow

# --- Stable CSV headers (order matters; the acquirer reads these) ---------------------------------

ELECTRICAL_CSV_COLUMNS: list[str] = [
    "node_id", "ts_utc", "ts_source", "phase",
    "voltage_v", "current_a", "power_w", "power_factor",
    "frequency_hz", "phase_angle_deg",
    "device_type", "firmware", "cadence_ms", "loc_tier", "loc_ref",
]

WEATHER_CSV_COLUMNS: list[str] = [
    "node_id", "time", "ts_source",
    "temp", "rhum", "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv",
    "device_type", "loc_tier", "loc_ref", "cell_id",
]

# Explicit allow-lists of node-record fields permitted into staging. Note the ABSENCE of postcode,
# raw_region, cell_id-derived-from-address, contributor_ref, token. By construction they can't leak.
_NODE_FIELDS_ELECTRICAL = ("device_type", "firmware", "cadence_ms", "loc_tier", "loc_ref")
# cell_id is a derived 0.25-deg grid key (coarse, non-identifying, same tier as loc_ref). It is
# computed server-side at registration where lat/lon exists, so the acquirer never needs coordinates.
_NODE_FIELDS_WEATHER = ("device_type", "loc_tier", "loc_ref", "cell_id")


def project_electrical(row: ElectricalRow, node: dict[str, Any]) -> dict[str, Any]:
    """Build a staging dict for one electrical row from the allow-list only."""
    out: dict[str, Any] = {
        "node_id": node["node_id"],
        "ts_utc": row.ts_utc,
        "ts_source": row.ts_source,
        "phase": row.phase,
        "voltage_v": row.voltage_v,
        "current_a": row.current_a,
        "power_w": row.power_w,
        "power_factor": row.power_factor,
        "frequency_hz": row.frequency_hz,
        "phase_angle_deg": row.phase_angle_deg,
    }
    for f in _NODE_FIELDS_ELECTRICAL:
        out[f] = node.get(f)
    return out


def project_weather(row: WeatherRow, node: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "node_id": node["node_id"],
        "time": row.time,
        "ts_source": row.ts_source,
        "temp": row.temp,
        "rhum": row.rhum,
        "wspd": row.wspd,
        "wdir": row.wdir,
        "pres": row.pres,
        "prcp": row.prcp,
        "solar_radiation_w_m2": row.solar_radiation_w_m2,
        "uv": row.uv,
    }
    for f in _NODE_FIELDS_WEATHER:
        out[f] = node.get(f)
    return out


# --- 0.25 degree cell snapping (matches GDA's weather cell grid) ----------------------------------

def cell_id_from_latlon(lat: float, lon: float) -> str:
    """Snap a point to GDA's 0.25 deg cell grid, centres at .125/.375/.625/.875.

    e.g. (51.40, -2.10) -> 'cell_51.375_-2.125'. Half-open intervals, matching GDA convention.
    """
    clat = math.floor(lat / 0.25) * 0.25 + 0.125
    clon = math.floor(lon / 0.25) * 0.25 + 0.125
    return f"cell_{clat:.3f}_{clon:.3f}"


# --- Location resolution (P0 stub, see module docstring) ------------------------------------------

# Coarse postcode-area -> GB DNO/GSP-ish region. Representative subset; defaults to GSP_UNKNOWN.
# TODO(P1): replace with GDA postcode_source.json + NESO_GIS point-in-polygon for true GSP group.
_POSTCODE_AREA_REGION: dict[str, str] = {
    "AB": "GSP_NORTH_SCOTLAND", "IV": "GSP_NORTH_SCOTLAND", "KW": "GSP_NORTH_SCOTLAND",
    "G": "GSP_CENTRAL_SCOTLAND", "EH": "GSP_SOUTH_SCOTLAND", "DD": "GSP_CENTRAL_SCOTLAND",
    "NE": "GSP_NORTH_EAST", "DH": "GSP_NORTH_EAST", "SR": "GSP_NORTH_EAST",
    "M": "GSP_NORTH_WEST", "L": "GSP_MERSEY", "PR": "GSP_NORTH_WEST",
    "LS": "GSP_YORKSHIRE", "S": "GSP_YORKSHIRE", "HD": "GSP_YORKSHIRE",
    "B": "GSP_MIDLANDS", "CV": "GSP_MIDLANDS", "WV": "GSP_MIDLANDS",
    "NG": "GSP_EAST_MIDLANDS", "LE": "GSP_EAST_MIDLANDS", "DE": "GSP_EAST_MIDLANDS",
    "NR": "GSP_EAST_ENGLAND", "CB": "GSP_EAST_ENGLAND", "IP": "GSP_EAST_ENGLAND",
    "N": "GSP_LONDON", "E": "GSP_LONDON", "SW": "GSP_LONDON", "SE": "GSP_LONDON",
    "W": "GSP_LONDON", "EC": "GSP_LONDON", "WC": "GSP_LONDON",
    "CF": "GSP_SOUTH_WALES", "SA": "GSP_SOUTH_WALES", "NP": "GSP_SOUTH_WALES",
    "BS": "GSP_SOUTH_WEST", "EX": "GSP_SOUTH_WEST", "PL": "GSP_SOUTH_WEST", "TR": "GSP_SOUTH_WEST",
    "SO": "GSP_SOUTHERN", "PO": "GSP_SOUTHERN", "RG": "GSP_SOUTHERN", "OX": "GSP_SOUTHERN",
    "ME": "GSP_SOUTH_EAST", "CT": "GSP_SOUTH_EAST", "TN": "GSP_SOUTH_EAST", "BN": "GSP_SOUTH_EAST",
}


def _postcode_area(postcode: str) -> str:
    """Leading letters of the outward code, e.g. 'BS1 5AH' -> 'BS'."""
    pc = postcode.strip().upper()
    letters = ""
    for ch in pc:
        if ch.isalpha():
            letters += ch
        else:
            break
    return letters


def resolve_location(
    *,
    loc_tier: str,
    postcode: str | None,
    region: str | None,
    client_ip: str | None,
    geoip_mmdb: Any | None = None,
) -> dict[str, str | None]:
    """Return {loc_ref, cell_id, stored_postcode, raw_region}. Only loc_ref/cell_id are ever staged.

    - anon:       derive a coarse region from IP (stub: None unless a geoip db is wired). No postcode.
    - region:     user-picked region -> loc_ref. No postcode.
    - data_share: postcode -> loc_ref (coarse area map for now). postcode kept private; cell needs
                  real geocoding (P1), so cell_id is None for now.
    """
    if loc_tier == "region":
        ref = f"DNO_{region}" if region else None
        return {"loc_ref": ref, "cell_id": None, "stored_postcode": None, "raw_region": None}

    if loc_tier == "data_share":
        ref = None
        if postcode:
            ref = _POSTCODE_AREA_REGION.get(_postcode_area(postcode), "GSP_UNKNOWN")
        # cell_id intentionally None until real postcode->lat/lon geocoding is wired (P1).
        return {"loc_ref": ref, "cell_id": None, "stored_postcode": postcode, "raw_region": None}

    # anon
    raw_region = _region_from_ip(client_ip, geoip_mmdb)
    return {"loc_ref": raw_region, "cell_id": None, "stored_postcode": None, "raw_region": raw_region}


def _region_from_ip(client_ip: str | None, geoip_mmdb: Any | None) -> str | None:
    """P0 stub. Real impl: MaxMind GeoLite2 lookup -> GB region. Returns None without a db."""
    if geoip_mmdb is None or client_ip is None:
        return None
    # TODO(P1): open the .mmdb once at startup and map subdivision -> GSP region.
    return None
