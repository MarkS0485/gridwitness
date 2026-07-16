"""Options flow (the settings panel): change sharing + location, and delete. Needs the HA harness."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gridwitness.const import (
    CONF_ALLOW_INSECURE,
    CONF_CHANNELS,
    CONF_LOC_REF,
    CONF_LOC_TIER,
    CONF_MAPPING,
    CONF_NODE_ID,
    CONF_SERVER_URL,
    CONF_TOKEN,
    DOMAIN,
)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="n1",
        data={
            CONF_SERVER_URL: "http://h:8000",
            CONF_ALLOW_INSECURE: True,
            CONF_NODE_ID: "n1",
            CONF_TOKEN: "t",
            CONF_CHANNELS: ["frequency_hz"],
            CONF_LOC_TIER: "anon",
            CONF_LOC_REF: None,
            CONF_MAPPING: {"frequency_hz": [{"entity_id": "sensor.f", "phase": "1p"}]},
        },
        options={},
    )


@contextmanager
def _patched(update_return):
    api = AsyncMock()
    api.update_consent = AsyncMock(return_value=update_return)
    api.delete_node = AsyncMock(return_value={"deleted": True})
    # Stub setup/unload so adding/removing the entry never starts the coordinator (no sockets).
    with patch("custom_components.gridwitness.config_flow.async_get_clientsession",
               return_value=MagicMock()), \
         patch("custom_components.gridwitness.config_flow.ApiClient", return_value=api), \
         patch("custom_components.gridwitness.async_setup_entry", return_value=True), \
         patch("custom_components.gridwitness.async_unload_entry", return_value=True):
        yield api


async def test_change_sharing_and_data_share_postcode(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    with _patched({"loc_ref": "GSP_SOUTH_WEST"}) as api:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.MENU
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "sharing"}
        )
        assert result["step_id"] == "sharing"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"share_frequency": True, "share_voltage": True, "share_current_power": False,
             "share_weather": False, "loc_tier": "data_share"},
        )
        assert result["step_id"] == "postcode"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"postcode": "BS1 5AH"}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY

    api.update_consent.assert_awaited_once()
    # the postcode reached the server call but is not persisted locally
    sent = api.update_consent.await_args.args[2]
    assert sent["postcode"] == "BS1 5AH" and sent["loc_tier"] == "data_share"
    assert set(entry.options[CONF_CHANNELS]) == {"frequency_hz", "voltage_v"}
    assert entry.options[CONF_LOC_TIER] == "data_share"
    assert entry.options[CONF_LOC_REF] == "GSP_SOUTH_WEST"


async def test_delete_requires_confirm(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    with _patched({}) as api:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "delete"}
        )
        assert result["step_id"] == "delete"
        # not confirming aborts without deleting
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"confirm": False}
        )
        assert result["type"] == FlowResultType.ABORT and result["reason"] == "delete_cancelled"
    api.delete_node.assert_not_awaited()
