"""Give-back sensors: your node vs the grid, contribution stats, sync health."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfFrequency, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NODE_ID, DOMAIN
from .coordinator import GridWitnessCoordinator


@dataclass(frozen=True, kw_only=True)
class GWSensorDescription(SensorEntityDescription):
    value_fn: Callable[[GridWitnessCoordinator], float | int | None]


SENSORS: tuple[GWSensorDescription, ...] = (
    GWSensorDescription(
        key="node_frequency",
        translation_key="node_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda c: c.last_frequency_hz,
    ),
    GWSensorDescription(
        key="clock_offset_ms",
        translation_key="clock_offset_ms",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.clock_offset_ms,
    ),
    GWSensorDescription(
        key="ntp_offset_ms",
        translation_key="ntp_offset_ms",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.ntp_offset_ms,
    ),
    GWSensorDescription(
        key="samples_today",
        translation_key="samples_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.samples_today,
    ),
    GWSensorDescription(
        key="samples_total",
        translation_key="samples_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.samples_total,
    ),
    GWSensorDescription(
        key="buffer_backlog",
        translation_key="buffer_backlog",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.buffer_backlog,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GridWitnessCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(GridWitnessSensor(coordinator, entry, desc) for desc in SENSORS)


class GridWitnessSensor(SensorEntity):
    _attr_has_entity_name = True
    entity_description: GWSensorDescription

    def __init__(
        self, coordinator: GridWitnessCoordinator, entry: ConfigEntry, desc: GWSensorDescription
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = desc
        node_id = entry.data[CONF_NODE_ID]
        self._attr_unique_id = f"{entry.entry_id}_{desc.key}"
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
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator)
