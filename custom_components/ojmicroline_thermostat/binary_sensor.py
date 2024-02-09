"""Miscellaneous binary sensors for OJ Microline thermostats."""
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
from .coordinator import OJMicrolineDataUpdateCoordinator
from .models import OJMicrolineEntity

BINARY_SENSOR_TYPES: list[BinarySensorEntityDescription] = [
    BinarySensorEntityDescription(
        name="Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        key="online",
    ),
    BinarySensorEntityDescription(
        name="Heating",
        icon="mdi:fire",
        key="heating",
    ),
    BinarySensorEntityDescription(
        name="Adaptive Mode",
        icon="mdi:brain",
        key="adaptive_mode",
    ),
    BinarySensorEntityDescription(
        name="Open Window Detection",
        icon="mdi:window-open",
        key="open_window_detection",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Load all OJMicroline Thermostat binary sensors.

    Args:
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.
    """

    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for idx, _ in coordinator.data.items():
        for description in BINARY_SENSOR_TYPES:
            # Different models of thermostat support different sensors;
            # skip creating entities if the value is None.
            if getattr(coordinator.data[idx], description.key) is not None:
                entities.append(OJMicrolineBinarySensor(coordinator, idx, description))

    async_add_entities(entities)


class OJMicrolineBinarySensor(OJMicrolineEntity, BinarySensorEntity):
    """Defines an OJ Microline Binary Sensor sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: OJMicrolineDataUpdateCoordinator,
        idx: str,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """
        Initialise the entity.

        Args:
            coordinator: The data coordinator updating the models.
            idx: The identifier for this entity.
            key: The key to get the sensor info from BINARY_SENSOR_TYPES.
        """
        super().__init__(coordinator, idx)

        self.entity_description = entity_description

        self._attr_unique_id = f"{idx}_{entity_description.key}"
        self._attr_name = f"{coordinator.data[idx].name} {entity_description.name}"

    @property
    def is_on(self) -> bool | None:
        """
        Return the status of the binary sensor.

        Returns:
            True if the sensor is on, false if not, unknown if it can't be reached.
        """
        return getattr(self.coordinator.data[self.idx], self.entity_description.key)
