"""Climate sensors for OJMicroline."""

import asyncio
import logging
from collections.abc import Mapping  # pylint: disable=import-error
from datetime import date
from typing import Any, ClassVar

import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import (
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
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
    ATTR_DAYS,
    ATTR_END_DATE,
    ATTR_EVENTS,
    ATTR_START_DATE,
    ATTR_TIME,
    CONF_COMFORT_MODE_DURATION,
    CONF_USE_COMFORT_MODE,
    DOMAIN,
    MANUFACTURER,
    PRESET_FROST_PROTECTION,
    PRESET_MANUAL,
    PRESET_SCHEDULE,
    PRESET_VACATION,
    SERVICE_CANCEL_VACATION,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_VACATION,
)
from .coordinator import OJMicrolineDataUpdateCoordinator
from .helpers import wd5_date
from .schedule import SLOTS, WEEKDAYS, ScheduleError, set_days

_LOGGER = logging.getLogger(__name__)

VENDOR_TO_HA_STATE = {
    REGULATION_SCHEDULE: PRESET_SCHEDULE,
    REGULATION_COMFORT: PRESET_COMFORT,
    REGULATION_MANUAL: PRESET_MANUAL,
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

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_VACATION,
        {
            vol.Required(ATTR_START_DATE): cv.date,
            vol.Required(ATTR_END_DATE): cv.date,
        },
        "async_set_vacation",
    )
    platform.async_register_entity_service(
        SERVICE_CANCEL_VACATION, {}, "async_cancel_vacation"
    )
    platform.async_register_entity_service(
        SERVICE_SET_SCHEDULE,
        {
            vol.Required(ATTR_DAYS): vol.All(
                cv.ensure_list, [vol.In(WEEKDAYS)], vol.Length(min=1)
            ),
            vol.Required(ATTR_EVENTS): vol.All(
                cv.ensure_list,
                [
                    vol.Schema(
                        {
                            vol.Required(ATTR_TIME): cv.time,
                            vol.Required(ATTR_TEMPERATURE): vol.Coerce(float),
                        }
                    )
                ],
                vol.Length(min=1, max=SLOTS),
            ),
        },
        "async_set_schedule",
    )


class OJMicrolineThermostat(
    CoordinatorEntity[OJMicrolineDataUpdateCoordinator], ClimateEntity
):
    """OJMicrolineThermostat climate."""

    _attr_hvac_modes: ClassVar[list[HVACMode]] = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "ojthermostat"

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
        """Return the current preset mode, e.g., schedule, manual.

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
    def max_temp(self) -> float:
        """Return max temperature.

        Returns
        -------
            The max temperature in a float format.

        """
        return self.coordinator.data[self.idx].max_temperature / 100

    @property
    def min_temp(self) -> float:
        """Return min temperature.

        Returns
        -------
            The min temperature in a float format.

        """
        return self.coordinator.data[self.idx].min_temperature / 100

    @property
    def hvac_action(self) -> HVACAction | None:
        """Indicates whether the thermostat is currently heating.

        Returns
        -------
            The HVACAction.

        """
        thermostat = self.coordinator.data[self.idx]
        if thermostat.heating:
            return HVACAction.HEATING
        if thermostat.online:
            return HVACAction.IDLE
        return HVACAction.OFF

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode.

        Args:
        ----
            preset_mode: The preset mode to set the thermostat to.

        """
        try:
            await self.coordinator.async_set_regulation_mode(
                self.coordinator.data[self.idx],
                HA_TO_VENDOR_STATE[preset_mode],
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

        regulation_mode = self.coordinator.data[self.idx].regulation_mode

        if regulation_mode not in {REGULATION_MANUAL, REGULATION_COMFORT}:
            regulation_mode = (
                REGULATION_COMFORT
                if self.options.get(CONF_USE_COMFORT_MODE)
                else REGULATION_MANUAL
            )

        await self.coordinator.async_set_regulation_mode(
            self.coordinator.data[self.idx],
            regulation_mode,
            temperature=round(temperature * 100),
            duration=self.options.get(CONF_COMFORT_MODE_DURATION),
        )
        await self._async_delayed_request_refresh()

    async def async_set_vacation(self, start_date: date, end_date: date) -> None:
        """Schedule a vacation for this thermostat's group.

        Args:
        ----
            start_date: The first day of the vacation.
            end_date: The day normal regulation resumes.

        """
        await self.coordinator.async_change_vacation(
            self.coordinator.data[self.idx], start_date, end_date, enabled=True
        )

    async def async_cancel_vacation(self) -> None:
        """Cancel the (scheduled or active) vacation for this thermostat's group."""
        thermostat = self.coordinator.data[self.idx]
        start = wd5_date(thermostat.vacation_begin_time)
        end = wd5_date(thermostat.vacation_end_time)
        if start is None or end is None or end <= start:
            msg = "Vacation can only be cancelled on WD5-series thermostats."
            raise ServiceValidationError(msg)
        await self.coordinator.async_change_vacation(
            thermostat, start, end, enabled=False
        )

    async def async_set_schedule(
        self, days: list[str], events: list[dict[str, Any]]
    ) -> None:
        """Set the events of one or more weekdays in the group's schedule.

        Args:
        ----
            days: The weekdays to change (monday ... sunday).
            events: The day's events, each with a time and a temperature.

        """
        thermostat = self.coordinator.data[self.idx]
        if thermostat.schedule is None:
            msg = "The schedule can only be set on WD5-series thermostats."
            raise ServiceValidationError(msg)
        try:
            schedule = set_days(
                thermostat.schedule,
                days,
                [(event[ATTR_TIME], event[ATTR_TEMPERATURE]) for event in events],
            )
        except ScheduleError as error:
            raise ServiceValidationError(str(error)) from error
        await self.coordinator.async_change_schedule(thermostat, schedule)

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

        Always ignore; we only support HEATING mode.

        Args:
        ----
            hvac_mode: Currently not used.

        """
        return True
