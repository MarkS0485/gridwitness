"""The GridWitness integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import ApiClient
from .buffer import DiskBuffer
from .const import (
    CONF_ALLOW_INSECURE,
    CONF_MAPPING,
    CONF_NODE_ID,
    CONF_SERVER_URL,
    CONF_TOKEN,
    DEFAULT_SERVER_URL,
    DOMAIN,
    MAX_BUFFER_AGE_H,
    MAX_BUFFER_ROWS,
)
from .coordinator import GridWitnessCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


def effective_config(entry: ConfigEntry) -> dict:
    """Entry data overlaid with options (options win — that's how reconfigure takes effect)."""
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = effective_config(entry)
    session = async_get_clientsession(hass)
    api = ApiClient(
        session,
        cfg.get(CONF_SERVER_URL, DEFAULT_SERVER_URL),
        allow_insecure=cfg.get(CONF_ALLOW_INSECURE, False),
    )
    node_id = cfg[CONF_NODE_ID]
    buffer_path = Path(hass.config.path(".storage", "gridwitness_buffer", f"{node_id}.ndjson"))
    buffer = DiskBuffer(buffer_path, max_rows=MAX_BUFFER_ROWS, max_age_h=MAX_BUFFER_AGE_H)

    coordinator = GridWitnessCoordinator(
        hass, api, buffer,
        node_id=node_id,
        token=cfg[CONF_TOKEN],
        mapping=cfg.get(CONF_MAPPING, {}),
    )
    coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: GridWitnessCoordinator | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
