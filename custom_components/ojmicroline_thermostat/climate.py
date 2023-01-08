"""Climate sensors for OJMicroline."""
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_HOME,
    PRESET_NONE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ojmicroline_thermostat import OJMicrolineException
from ojmicroline_thermostat.const import (
    REGULATION_BOOST,
    REGULATION_COMFORT,
    REGULATION_ECO,
    REGULATION_FROST_PROTECTION,
    REGULATION_MANUAL,
    REGULATION_SCHEDULE,
    REGULATION_VACATION,
)

from .const import DOMAIN, MANUFACTURER, PRESET_FROST_PROTECTION, PRESET_VACATION
from .coordinator import OJMicrolineDataUpdateCoordinator

MODE_LIST = [HVACMode.HEAT, HVACMode.AUTO]
PRESET_LIST = [
    PRESET_HOME,
    PRESET_COMFORT,
    PRESET_NONE,
    PRESET_VACATION,
    PRESET_FROST_PROTECTION,
    PRESET_BOOST,
    PRESET_ECO,
]

_LOGGER = logging.getLogger(__name__)

VENDOR_TO_HA_STATE = {
    REGULATION_SCHEDULE: PRESET_HOME,
    REGULATION_COMFORT: PRESET_COMFORT,
    REGULATION_MANUAL: PRESET_NONE,
    REGULATION_VACATION: PRESET_VACATION,
    REGULATION_FROST_PROTECTION: PRESET_FROST_PROTECTION,
    REGULATION_BOOST: PRESET_BOOST,
    REGULATION_ECO: PRESET_ECO,
}
HA_TO_VENDOR_STATE = {v: k for k, v in VENDOR_TO_HA_STATE.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    Load all OJMicroline Thermostat devices.

    Args:
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for idx, _ in coordinator.data.items():
        entities.append(OJMicrolineThermostat(coordinator, idx))
    async_add_entities(entities)


class OJMicrolineThermostat(
    CoordinatorEntity[OJMicrolineDataUpdateCoordinator], ClimateEntity
):
    """OJMicrolineThermostat climate."""

    _attr_hvac_modes = MODE_LIST
    _attr_preset_modes = PRESET_LIST
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_temperature_unit = TEMP_CELSIUS
    _attr_has_entity_name = True

    idx = str

    def __init__(self, coordinator: OJMicrolineDataUpdateCoordinator, idx: str) -> None:
        """
        Initialise the entity.

        Args:
            coordinator: The data coordinator updating the models.
            idx: The identifier for this entity.
        """
        super().__init__(coordinator)
        self.idx = idx
        self._attr_unique_id = self.idx

    @property
    def device_info(self) -> DeviceInfo:
        """
        Set up the device information for this thermostat.

        Returns:
            The device identifiers to make sure the entity is attached
            to the correct device.
        """
        return DeviceInfo(
            identifiers={(DOMAIN, self.idx)},
            manufacturer=MANUFACTURER,
            name=self.coordinator.data[self.idx].name,
            sw_version=self.coordinator.data[self.idx].software_version,
            model=self.coordinator.data[self.idx].model,
        )

    @property
    def preset_mode(self) -> str:
        """
        Return the current preset mode, e.g., home, away.

        Returns:
            The preset mode in a string format.
        """
        return VENDOR_TO_HA_STATE.get(self.coordinator.data[self.idx].regulation_mode)

    @property
    def current_temperature(self) -> float:
        """
        Return current temperature.

        Returns:
            The current temperature in a float format..
        """
        return self.coordinator.data[self.idx].get_current_temperature() / 100

    @property
    def target_temperature(self) -> float:
        """
        Return target temperature.

        Returns:
            The target temperature in a float format.
        """
        return self.coordinator.data[self.idx].get_target_temperature() / 100

    @property
    def target_temperature_high(self) -> float:
        """
        Return max temperature.

        Returns:
            The max temperature in a float format.
        """
        return self.coordinator.data[self.idx].max_temperature / 100

    @property
    def target_temperature_low(self) -> float:
        """
        Return target temperature.

        Returns:
            The target temperature in a float format.
        """
        return self.coordinator.data[self.idx].min_temperature / 100

    @property
    def hvac_mode(self):
        """
        Return the hvac operation ie. heat, cool mode.

        Returns:
            The HVACMode.

        """
        if self.coordinator.data[self.idx].heating:
            return HVACMode.HEAT

        return HVACMode.AUTO

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """
        Set new preset mode.

        Args:
            preset_mode: The preset mode to set the thermostat to.
        """
        try:
            await self.coordinator.api.set_regulation_mode(
                self.coordinator.data[self.idx],
                HA_TO_VENDOR_STATE.get(preset_mode),
            )
            await self.coordinator.async_request_refresh()
        except OJMicrolineException as error:
            _LOGGER.error(
                'Failed setting preset mode "%s" (%s) %s',
                self.coordinator.data[self.idx].name,
                preset_mode,
                error,
            )

    async def async_set_temperature(self, **kwargs) -> None:
        """
        Set new temperature.

        Args:
            **kwargs: All arguments passed to the method.
        """
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        await self.coordinator.api.set_regulation_mode(
            self.coordinator.data[self.unique_id],
            REGULATION_COMFORT,
            int(temperature * 100),
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, _hvac_mode: str) -> bool:
        """
        Set new hvac mode.

        Always set to schedule as we cannot control the heating.

        Args:
            _hvac_mode: Currently not used.
        """

        await self.async_set_preset_mode(PRESET_HOME)
