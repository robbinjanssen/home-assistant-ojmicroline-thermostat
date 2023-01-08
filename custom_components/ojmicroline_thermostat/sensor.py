"""Support for Xiaomi Aqara sensors."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from ojmicroline_thermostat.const import SENSOR_FLOOR, SENSOR_ROOM, SENSOR_ROOM_FLOOR

from .const import DOMAIN, MODE_FLOOR, MODE_ROOM, MODE_ROOM_FLOOR
from .coordinator import OJMicrolineDataUpdateCoordinator
from .models import OJMicrolineEntity

VENDOR_TO_HA_STATE = {
    SENSOR_FLOOR: MODE_FLOOR,
    SENSOR_ROOM: MODE_ROOM,
    SENSOR_ROOM_FLOOR: MODE_ROOM_FLOOR,
}

SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    "temperature_room": SensorEntityDescription(
        name="Temperature Room",
        icon="mdi:home-thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        key="temperature_room",
    ),
    "temperature_floor": SensorEntityDescription(
        name="Temperature Floor",
        icon="mdi:heating-coil",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        key="temperature_floor",
    ),
    "min_temperature": SensorEntityDescription(
        name="Temperature Range Min",
        icon="mdi:thermometer-chevron-down",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        key="min_temperature",
    ),
    "max_temperature": SensorEntityDescription(
        name="Temperature Range Max",
        icon="mdi:thermometer-chevron-up",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        key="max_temperature",
    ),
    "temperature_set_point": SensorEntityDescription(
        name="Temperature Set Point",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        key="temperature_set_point",
    ),
    "sensor_mode": SensorEntityDescription(
        name="Sensor Mode", icon="mdi:thermometer-lines", key="sensor_mode"
    ),
    "boost_end_time": SensorEntityDescription(
        name="Boost End Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=SensorStateClass.MEASUREMENT,
        key="boost_end_time",
    ),
    "comfort_end_time": SensorEntityDescription(
        name="Comfort End Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=SensorStateClass.MEASUREMENT,
        key="comfort_end_time",
    ),
    "vacation_begin_time": SensorEntityDescription(
        name="Vacation Begin Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=SensorStateClass.MEASUREMENT,
        key="vacation_begin_time",
    ),
    "vacation_end_time": SensorEntityDescription(
        name="Vacation End Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=SensorStateClass.MEASUREMENT,
        key="vacation_end_time",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Load all OJMicroline Thermostat sensors.

    Args:
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.
    """

    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for idx, _ in coordinator.data.items():
        for key in SENSOR_TYPES:
            entities.append(OJMicrolineSensor(coordinator, idx, key))

    async_add_entities(entities)


class OJMicrolineSensor(OJMicrolineEntity, SensorEntity):
    """Defines an OJ Microline Sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: OJMicrolineDataUpdateCoordinator,
        idx: str,
        key: str,
    ):
        """
        Initialise the entity.

        Args:
            coordinator: The data coordinator updating the models.
            idx: The identifier for this entity.
            key: The key to get the sensor info from BINARY_SENSOR_TYPES.
        """
        super().__init__(coordinator, idx)

        self.entity_description = SENSOR_TYPES[key]

        self._attr_unique_id = f"{idx}_{key}"
        self._attr_name = f"{coordinator.data[idx].name} {self.entity_description.name}"

    @property
    def available(self) -> bool:
        """
        Get the availability status.

        Returns:
            True if the sensor is available, false otherwise.
        """
        return self.coordinator.data[self.idx].online

    @property
    def native_value(self) -> Any | None:
        """
        Return the state of the sensor.

        Returns:
            The current state value of the sensor.
        """

        if self.entity_description.key in (
            "temperature_room",
            "temperature_floor",
            "min_temperature",
            "max_temperature",
        ):
            return (
                getattr(self.coordinator.data[self.idx], self.entity_description.key)
                / 100
            )

        if self.entity_description.key in (
            "boost_end_time",
            "comfort_end_time",
            "vacation_begin_time",
            "vacation_end_time",
        ):
            target_date = getattr(
                self.coordinator.data[self.idx], self.entity_description.key
            )
            now = datetime.now(target_date.tzinfo)

            if now > target_date:
                return None

            return target_date

        if self.entity_description.key == "temperature_set_point":
            return self.coordinator.data[self.idx].get_target_temperature() / 100

        if self.entity_description.key == "sensor_mode":
            return VENDOR_TO_HA_STATE.get(
                getattr(self.coordinator.data[self.idx], self.entity_description.key)
            )

        return getattr(self.coordinator.data[self.idx], self.entity_description.key)
