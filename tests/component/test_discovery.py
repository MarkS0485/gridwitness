"""Discovery groups entities by device_class and infers phase. Needs the HA test harness."""
from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.gridwitness.discovery import discover, propose_mapping


async def _add(hass, entity_id: str, device_class: str, value: str = "1.0") -> None:
    registry = er.async_get(hass)
    unique = entity_id.split(".", 1)[1]
    registry.async_get_or_create("sensor", "gridwitness_test", unique, suggested_object_id=unique)
    hass.states.async_set(entity_id, value, {"device_class": device_class})


async def test_groups_and_phase_inference(hass):
    await _add(hass, "sensor.meter_l1_power", "power")
    await _add(hass, "sensor.meter_l2_power", "power")
    await _add(hass, "sensor.meter_l3_power", "power")
    await _add(hass, "sensor.grid_frequency", "frequency", "50.01")
    await _add(hass, "sensor.garden_temperature", "temperature", "14.2")
    await hass.async_block_till_done()

    disco = discover(hass)
    assert disco.has_any()
    # frequency is node-global -> phase 1p
    freq = disco.groups["frequency"]
    assert len(freq) == 1 and freq[0].phase == "1p" and freq[0].channel == "frequency_hz"
    # three power phases inferred
    phases = sorted(c.phase for c in disco.groups["current_power"])
    assert phases == ["L1", "L2", "L3"]
    # weather bucketed
    assert disco.groups["weather"][0].channel == "temp"


async def test_propose_mapping_single_frequency(hass):
    await _add(hass, "sensor.freq_a", "frequency", "50.0")
    await _add(hass, "sensor.freq_b", "frequency", "50.0")
    await hass.async_block_till_done()
    mapping = propose_mapping(discover(hass))
    assert len(mapping["frequency_hz"]) == 1  # only one node-global frequency kept
