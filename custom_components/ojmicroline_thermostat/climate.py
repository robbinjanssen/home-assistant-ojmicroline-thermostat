"""Climate sensors for OJMicroline."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

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
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ojmicroline_thermostat import OJMicrolineError
from ojmicroline_thermostat.const import (
    REGULATION_BOOST,
    REGULATION_COMFORT,
    REGULATION_ECO,
    REGULATION_FROST_PROTECTION,
    REGULATION_MANUAL,
    REGULATION_SCHEDULE,
    REGULATION_VACATION,
)

from .const import (
    CONF_COMFORT_MODE_DURATION,
    CONF_USE_COMFORT_MODE,
    DOMAIN,
    MANUFACTURER,
    PRESET_FROST_PROTECTION,
    PRESET_VACATION,
)
from .coordinator import OJMicrolineDataUpdateCoordinator

MODE_LIST = [HVACMode.HEAT, HVACMode.AUTO]

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
    """Load all OJMicroline Thermostat devices.

    Args:
    ----
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.

    """
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for idx in coordinator.data:
        entities.append(  # noqa: PERF401
            OJMicrolineThermostat(
                coordinator=coordinator, idx=idx, options=entry.options
            )
        )
    async_add_entities(entities)


class OJMicrolineThermostat(
    CoordinatorEntity[OJMicrolineDataUpdateCoordinator], ClimateEntity
):
    """OJMicrolineThermostat climate."""

    _attr_hvac_modes = MODE_LIST
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = None

    idx: str
    options: Mapping[str, Any]

    def __init__(
        self,
        coordinator: OJMicrolineDataUpdateCoordinator,
        idx: str,
        options: Mapping[str, Any],
    ) -> None:
        """Initialise the entity.

        Args:
        ----
            coordinator: The data coordinator updating the models.
            idx: The identifier for this entity.
            options: The options provided by the user.

        """
        super().__init__(coordinator)
        self.idx = idx
        self.options = options
        self._attr_unique_id = self.idx

    @property
    def device_info(self) -> DeviceInfo:
        """Set up the device information for this thermostat.

        Returns
        -------
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
    def preset_modes(self) -> list[str] | None:
        """Return a list of available preset modes.

        Returns
        -------
            A list of supported preset modes in string format.

        """
        return [
            VENDOR_TO_HA_STATE[mode]
            for mode in self.coordinator.data[self.idx].supported_regulation_modes
        ]

    @property
    def preset_mode(self) -> str:
        """Return the current preset mode, e.g., home, away.

        Returns
        -------
            The preset mode in a string format.

        """
        return VENDOR_TO_HA_STATE.get(self.coordinator.data[self.idx].regulation_mode)  # type: ignore[return-value]

    @property
    def current_temperature(self) -> float:
        """Return current temperature.

        Returns
        -------
            The current temperature in a float format..

        """
        return self.coordinator.data[self.idx].get_current_temperature() / 100

    @property
    def target_temperature(self) -> float:
        """Return target temperature.

        Returns
        -------
            The target temperature in a float format.

        """
        return self.coordinator.data[self.idx].get_target_temperature() / 100

    @property
    def target_temperature_high(self) -> float:
        """Return max temperature.

        Returns
        -------
            The max temperature in a float format.

        """
        return self.coordinator.data[self.idx].max_temperature / 100

    @property
    def target_temperature_low(self) -> float:
        """Return target temperature.

        Returns
        -------
            The target temperature in a float format.

        """
        return self.coordinator.data[self.idx].min_temperature / 100

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the hvac operation ie. heat, cool mode.

        Returns
        -------
            The HVACMode.

        """
        if self.coordinator.data[self.idx].heating:
            return HVACMode.HEAT

        return HVACMode.AUTO

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode.

        Args:
        ----
            preset_mode: The preset mode to set the thermostat to.

        """
        try:
            await self.coordinator.api.set_regulation_mode(
                self.coordinator.data[self.idx],
                HA_TO_VENDOR_STATE.get(preset_mode),
            )
            await self._async_delayed_request_refresh()
        except OJMicrolineError:
            _LOGGER.exception(
                'Failed setting preset mode "%s" (%s)',
                self.coordinator.data[self.idx].name,
                preset_mode,
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new temperature.

        Args:
        ----
            **kwargs: All arguments passed to the method.

        """
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        regulation_mode = REGULATION_MANUAL
        if self.options.get(CONF_USE_COMFORT_MODE) is True:
            regulation_mode = REGULATION_COMFORT

        await self.coordinator.api.set_regulation_mode(
            resource=self.coordinator.data[self.unique_id],
            regulation_mode=regulation_mode,
            temperature=int(temperature * 100),
            duration=self.options.get(CONF_COMFORT_MODE_DURATION),
        )
        await self._async_delayed_request_refresh()

    async def _async_delayed_request_refresh(self) -> None:
        """Get delayed data from the coordinator.

        Refreshing immediately after an API call can return stale data,
        probably due to DB propagation on the API backend.

        The *ideal* fix would be to switch away from polling; the API
        does support some sort of HTTP-long-poll notification mechanism.

        As a temporary band-aid, sleep for 2 seconds and then request a
        refresh. Manual testing indicates this seems to work well enough;
        1 second was verified to be too short.
        """
        await asyncio.sleep(2)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(
        self,
        hvac_mode: str,  # pylint: disable=unused-argument  # noqa: ARG002
    ) -> bool:
        """Set new hvac mode.

        Always set to schedule as we cannot control the heating.

        Args:
        ----
            hvac_mode: Currently not used.

        """
        await self.async_set_preset_mode(PRESET_HOME)
        return True
