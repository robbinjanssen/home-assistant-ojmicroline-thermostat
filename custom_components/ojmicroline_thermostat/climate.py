"""Climate sensors for OJMicroline."""

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import probatio
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
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
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
    CONF_COMFORT_TEMPERATURE,
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
from .coordinator import OJMicrolineConfigEntry, OJMicrolineDataUpdateCoordinator
from .helpers import target_temperature, wd5_date
from .schedule import SLOTS, WEEKDAYS, ScheduleError, set_days

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from ojmicroline_thermostat import Thermostat

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
    _hass: HomeAssistant,
    entry: OJMicrolineConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load all OJMicroline Thermostat devices.

    Args:
    ----
        _hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.

    """
    coordinator = entry.runtime_data
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
            probatio.Required(ATTR_START_DATE): cv.date,
            probatio.Required(ATTR_END_DATE): cv.date,
        },
        "async_set_vacation",
    )
    platform.async_register_entity_service(
        SERVICE_CANCEL_VACATION, {}, "async_cancel_vacation"
    )
    platform.async_register_entity_service(
        SERVICE_SET_SCHEDULE,
        {
            probatio.Required(ATTR_DAYS): probatio.All(
                cv.ensure_list, [probatio.In(WEEKDAYS)], probatio.Length(min=1)
            ),
            probatio.Required(ATTR_EVENTS): probatio.All(
                cv.ensure_list,
                [
                    probatio.Schema(
                        {
                            probatio.Required(ATTR_TIME): cv.time,
                            probatio.Required(ATTR_TEMPERATURE): probatio.Coerce(float),
                        }
                    )
                ],
                probatio.Length(min=1, max=SLOTS),
            ),
        },
        "async_set_schedule",
    )


class OJMicrolineThermostat(
    CoordinatorEntity[OJMicrolineDataUpdateCoordinator], ClimateEntity
):
    """OJMicrolineThermostat climate."""

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
        self._attr_hvac_modes = [HVACMode.HEAT]
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
        return target_temperature(self.coordinator.data[self.idx]) / 100

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
        thermostat = self.coordinator.data[self.idx]
        regulation_mode = HA_TO_VENDOR_STATE[preset_mode]
        # Always send a temperature for these presets: without one, the WG4
        # API stores an empty temperature and the thermostat falls back to an
        # unrelated value (issue #280).
        temperature = None
        if regulation_mode == REGULATION_MANUAL:
            temperature = target_temperature(thermostat)
        elif regulation_mode == REGULATION_COMFORT:
            temperature = self._comfort_temperature(thermostat)
        try:
            await self._async_set_regulation_mode(regulation_mode, temperature)
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

        await self._async_set_regulation_mode(regulation_mode, round(temperature * 100))

    def _comfort_temperature(self, thermostat: Thermostat) -> int:
        """Return the temperature to use for the comfort preset, in 1/100 °C.

        The configured comfort temperature, otherwise the comfort temperature
        stored in the thermostat, and as a last resort the current target.
        """
        if (configured := self.options.get(CONF_COMFORT_TEMPERATURE)) is not None:
            return round(float(configured) * 100)
        stored: int | None = thermostat.comfort_temperature
        return stored or target_temperature(thermostat)

    async def _async_set_regulation_mode(
        self, regulation_mode: int, temperature: int | None
    ) -> None:
        """Set the regulation mode and show it right away.

        The new mode is applied to the coordinator data immediately, so the
        state does not wait for the API, and the refresh that confirms it
        runs in the background.

        Raises
        ------
            OJMicrolineError: The API refused the update.

        """
        thermostat = self.coordinator.data[self.idx]
        await self.coordinator.async_set_regulation_mode(
            thermostat,
            regulation_mode,
            temperature=temperature,
            duration=self.options.get(CONF_COMFORT_MODE_DURATION),
        )

        changes: dict[str, Any] = {"regulation_mode": regulation_mode}
        if temperature is not None:
            if regulation_mode == REGULATION_MANUAL:
                changes["manual_temperature"] = temperature
            elif regulation_mode == REGULATION_COMFORT:
                changes["comfort_temperature"] = temperature
            if thermostat.set_point_temperature is not None:
                changes["set_point_temperature"] = temperature
        self.coordinator.async_set_updated_data(
            {**self.coordinator.data, self.idx: replace(thermostat, **changes)}
        )
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self._async_delayed_request_refresh(),
            f"Refresh {thermostat.name} after an update",
        )

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
        hvac_mode: HVACMode,  # pylint: disable=unused-argument
    ) -> None:
        """Set new hvac mode.

        Always ignore; we only support HEATING mode.

        Args:
        ----
            hvac_mode: Currently not used.

        """
