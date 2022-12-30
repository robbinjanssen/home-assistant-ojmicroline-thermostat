"""Support for OJ Microline binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .models import OJMicrolineEntity
from .coordinator import OJMicrolineDataUpdateCoordinator

BINARY_SENSOR_TYPES: dict[str, BinarySensorEntityDescription] = {
    "online": BinarySensorEntityDescription(
        name="Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        state_key="online",
    ),
    "heating": BinarySensorEntityDescription(
        name="Heating",
        icon="mdi:fire",
        state_key="heating",
    ),
    "adaptive_mode": BinarySensorEntityDescription(
        name="Adaptive Mode",
        icon="mdi:brain",
        state_key="adaptive_mode",
    ),
    "open_window_detection": BinarySensorEntityDescription(
        name="Open Window Detection",
        icon="mdi:window-open",
        state_key="open_window_detection",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all OJ Microline binary sensors for all thermostat."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for idx, _resource in coordinator.data.items():
        for key in BINARY_SENSOR_TYPES:
            entities.append(OJMicrolineBinarySensor(coordinator, idx, key))

    async_add_entities(entities)


class OJMicrolineBinarySensor(OJMicrolineEntity, BinarySensorEntity):
    """Defines an OJ Microline Binary Sensor sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: OJMicrolineDataUpdateCoordinator,
        idx: str,
        key: str,
    ) -> None:
        """Call parent init()"""
        super().__init__(coordinator, idx)

        """Initialize the sensor."""
        self.entity_description = BINARY_SENSOR_TYPES[key]

        self._attr_unique_id = f"{idx}_{key}"
        self._attr_name = f"{coordinator.data[idx].name} {self.entity_description.name}"

    @property
    def is_on(self) -> bool | None:
        """Return the status of the binary sensor."""
        return getattr(
            self.coordinator.data[self.idx],
            self.entity_description.state_key
        )
