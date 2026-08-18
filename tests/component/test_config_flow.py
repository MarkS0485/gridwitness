"""Config + options flow. Needs the HA test harness (pytest-homeassistant-custom-component)."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.gridwitness.const import (
    CONF_CHANNELS,
    CONF_LOC_TIER,
    CONF_NODE_ID,
    DOMAIN,
)
from custom_components.gridwitness.discovery import Candidate, Discovery

_FAKE_DISCO = Discovery(groups={
    "frequency": [Candidate("sensor.grid_frequency", "frequency_hz", "1p", "frequency", "Grid")],
    "voltage": [], "current_power": [], "weather": [],
})


def _patched_api(register_return):
    api = AsyncMock()
    api.register = AsyncMock(return_value=register_return)
    return api


@contextmanager
def _patched_flow(register_return):
    """Patch the flow's collaborators, and stub async_setup_entry so creating the entry does not run
    real setup (which would start the coordinator's NTP task and touch a socket)."""
    with patch("custom_components.gridwitness.config_flow.discover", return_value=_FAKE_DISCO), \
         patch("custom_components.gridwitness.config_flow.async_get_clientsession",
               return_value=MagicMock()), \
         patch("custom_components.gridwitness.config_flow.ApiClient",
               return_value=_patched_api(register_return)), \
         patch("custom_components.gridwitness.async_setup_entry", return_value=True):
        yield


async def test_user_flow_frequency_anon(hass):
    with _patched_flow({"node_id": "abcd1234ef", "token": "tok", "loc_ref": None}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"server_url": "http://localhost:8000", "allow_insecure": True}
        )
        assert result["step_id"] == "consent"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"share_frequency": True, "share_voltage": False,
             "share_current_power": False, "share_weather": False, "loc_tier": "anon"},
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_NODE_ID] == "abcd1234ef"
        assert result["data"][CONF_CHANNELS] == ["frequency_hz"]
        assert result["data"][CONF_LOC_TIER] == "anon"


async def test_data_share_asks_for_postcode(hass):
    with _patched_flow({"node_id": "n2", "token": "t2", "loc_ref": "GSP_SOUTH_WEST"}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"server_url": "http://h:8000", "allow_insecure": True}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"share_frequency": True, "share_voltage": False,
             "share_current_power": False, "share_weather": False, "loc_tier": "data_share"},
        )
        assert result["step_id"] == "postcode"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"postcode": "BS1 5AH"}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
