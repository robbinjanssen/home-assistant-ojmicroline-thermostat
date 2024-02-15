"""Miscellaneous sensors for OJ Microline thermostats."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature

from ojmicroline_thermostat import Thermostat
from ojmicroline_thermostat.const import SENSOR_FLOOR, SENSOR_ROOM, SENSOR_ROOM_FLOOR

from .const import DOMAIN, MODE_FLOOR, MODE_ROOM, MODE_ROOM_FLOOR
from .models import OJMicrolineEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OJMicrolineDataUpdateCoordinator


VENDOR_TO_HA_STATE = {
    SENSOR_FLOOR: MODE_FLOOR,
    SENSOR_ROOM: MODE_ROOM,
    SENSOR_ROOM_FLOOR: MODE_ROOM_FLOOR,
}

# A sensor's value is passed through a function of this type to format it.
ValueFormatter = Callable[[Any], Any]

# By default, a sensor's value is fetched from the Thermostat using getattr
# with the sensor description's key. This can be overridden using this type.
ValueGetterOverride = Callable[[Thermostat], Any]


@dataclass
class OJMicrolineSensorInfo:
    """Describes a sensor for the OJ Microline thermostat.

    In addition to a SensorEntityDescription for Home Assistant, it includes a
    Callable that can format the raw value and an optional Callable to fetch
    the raw value (overriding the default behavior of using the entity
    description's key).
    """

    entity_description: SensorEntityDescription
    formatter: ValueFormatter
    # Defaults to getattr on the key if None
    value_getter: ValueGetterOverride | None = None


def _get_value(
    thermostat: Thermostat,
    desc: SensorEntityDescription,
    value_getter: ValueGetterOverride | None,
) -> Any:
    """Fetch a value from the thermostat by using the getter override.

    If it exists, use it, otherwise it fetches the value using getattr
    with the description's key.
    """
    if value_getter:
        return value_getter(thermostat)
    return getattr(thermostat, desc.key)


def _temp_formatter(temp: Any) -> float:
    """Format the temperature."""
    return temp / 100


def _date_formatter(dt: Any) -> datetime | None:
    """Format the date."""
    now = datetime.now(dt.tzinfo)
    if now > dt:
        return None
    return dt


SENSOR_TYPES: list[OJMicrolineSensorInfo] = [
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Temperature Room",
            icon="mdi:home-thermometer",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            key="temperature_room",
        ),
        _temp_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Temperature Floor",
            icon="mdi:heating-coil",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            key="temperature_floor",
        ),
        _temp_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Temperature Range Min",
            icon="mdi:thermometer-chevron-down",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            key="min_temperature",
        ),
        _temp_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Temperature Range Max",
            icon="mdi:thermometer-chevron-up",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            key="max_temperature",
        ),
        _temp_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Temperature Set Point",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            key="temperature_set_point",
        ),
        _temp_formatter,
        lambda thermostat: thermostat.get_target_temperature(),
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Sensor Mode", icon="mdi:thermometer-lines", key="sensor_mode"
        ),
        VENDOR_TO_HA_STATE.get,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Boost End Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            key="boost_end_time",
        ),
        _date_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Comfort End Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            key="comfort_end_time",
        ),
        _date_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Vacation Begin Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            key="vacation_begin_time",
        ),
        _date_formatter,
    ),
    OJMicrolineSensorInfo(
        SensorEntityDescription(
            name="Vacation End Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            key="vacation_end_time",
        ),
        _date_formatter,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load all OJMicroline Thermostat sensors.

    Args:
    ----
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.

    """
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for idx in coordinator.data.keys():  # noqa: SIM118
        for info in SENSOR_TYPES:
            # Different models of thermostat support different sensors;
            # skip creating entities if the value is None.
            val = _get_value(
                coordinator.data[idx], info.entity_description, info.value_getter
            )
            if val is not None:
                entities.append(
                    OJMicrolineSensor(
                        coordinator,
                        idx,
                        info.entity_description,
                        info.formatter,
                        info.value_getter,
                    )
                )

    async_add_entities(entities)


class OJMicrolineSensor(OJMicrolineEntity, SensorEntity):
    """Defines an OJ Microline Sensor."""

    entity_description: SensorEntityDescription
    formatter: ValueFormatter
    value_getter: ValueGetterOverride | None

    def __init__(  # pylint: disable=too-many-arguments  # noqa: PLR0913
        self,
        coordinator: OJMicrolineDataUpdateCoordinator,
        idx: str,
        entity_description: SensorEntityDescription,
        formatter: ValueFormatter,
        value_getter: ValueGetterOverride | None,
    ) -> None:
        """Initialise the entity.

        Args:
        ----
            coordinator: The data coordinator updating the models.
            idx: The identifier for this entity.
            key: The key to get the sensor info from BINARY_SENSOR_TYPES.

        """
        super().__init__(coordinator, idx)

        self.entity_description = entity_description
        self.formatter = formatter
        self.value_getter = value_getter

        self._attr_unique_id = f"{idx}_{self.entity_description.key}"
        self._attr_name = f"{coordinator.data[idx].name} {self.entity_description.name}"

    @property
    def available(self) -> bool:
        """Get the availability status.

        Returns
        -------
            True if the sensor is available, false otherwise.

        """
        return self.coordinator.data[self.idx].online

    @property
    def native_value(self) -> Any | None:
        """Return the state of the sensor.

        Returns
        -------
            The current state value of the sensor.

        """
        thermostat = self.coordinator.data[self.idx]
        val = _get_value(thermostat, self.entity_description, self.value_getter)
        return self.formatter(val)
