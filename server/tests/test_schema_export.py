"""The published schema artifacts stay consistent with the models."""
from __future__ import annotations

import json
from pathlib import Path

from gridwitness_server import models
from gridwitness_server.schema_export import build_channels, build_ingest_schema

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"


def test_channel_catalogue_matches_committed_file():
    # channels.v1.json is generated directly from CHANNEL_CATALOGUE (no pydantic version dependence),
    # so an exact match is a robust drift guard.
    committed = json.loads((_SCHEMA_DIR / "channels.v1.json").read_text(encoding="utf-8"))
    assert committed == build_channels(), "schema/channels.v1.json is stale; regenerate it"


def test_every_channel_is_documented_with_required_keys():
    for name in models.ALL_CHANNELS:
        entry = models.CHANNEL_CATALOGUE[name]
        assert {"kind", "unit", "type", "sensitivity", "description"} <= set(entry)
        assert entry["kind"] in ("electrical", "weather")
        assert entry["sensitivity"] in ("none", "low", "high")


def test_catalogue_partitions_match_row_models():
    # the electrical/weather split in the catalogue must match the actual row model fields
    elec_fields = set(models.ElectricalRow.model_fields) - {"ts_utc", "ts_source", "phase"}
    weather_fields = set(models.WeatherRow.model_fields) - {"time", "ts_source"}
    assert models.ELECTRICAL_CHANNELS == elec_fields
    assert models.WEATHER_CHANNELS == weather_fields


def test_ingest_schema_has_all_models_and_versioning():
    schema = build_ingest_schema()
    assert schema["gridwitnessSchemaVersion"] == models.SCHEMA_VERSION
    defs = schema["$defs"]
    for model in ("RegisterRequest", "RegisterResponse", "SamplesRequest", "SamplesResponse",
                  "ElectricalRow", "WeatherRow"):
        assert model in defs, model
    assert defs["ElectricalRow"]["properties"]["phase"]["enum"] == ["L1", "L2", "L3", "1p"]
    assert "producer" in defs["RegisterRequest"]["properties"]
    assert "schema_version" in defs["SamplesRequest"]["properties"]
