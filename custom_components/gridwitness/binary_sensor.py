"""Online/offline binary sensor for the node's link to the ingest server."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NODE_ID, DOMAIN
from .coordinator import GridWitnessCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GridWitnessCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GridWitnessOnline(coordinator, entry)])


class GridWitnessOnline(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: GridWitnessCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        node_id = entry.data[CONF_NODE_ID]
        self._attr_unique_id = f"{entry.entry_id}_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, node_id)},
            name=f"GridWitness node {node_id[:8]}",
            manufacturer="GridWitness",
            model="Crowd grid node",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.online
