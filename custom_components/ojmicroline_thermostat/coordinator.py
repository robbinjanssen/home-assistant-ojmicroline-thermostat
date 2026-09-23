"""OJMicroline Thermostat platform configuration."""

import asyncio
import logging
from dataclasses import replace
from datetime import date, timedelta
from time import monotonic
from typing import Any

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ojmicroline_thermostat import (
    WD5API,
    OJMicrolineAuthError,
    OJMicrolineError,
    Thermostat,
)
from ojmicroline_thermostat.const import (
    COMFORT_DURATION,
    REGULATION_BOOST,
    REGULATION_COMFORT,
    REGULATION_MANUAL,
    REGULATION_SCHEDULE,
    REGULATION_VACATION,
)
from ojmicroline_thermostat.ojmicroline import SessionOJMicrolineAPI

from .api import api_from_config_entry_data, oj_microline_from_api
from .const import (
    API_TIMEOUT,
    DOMAIN,
    ENERGY_UPDATE_INTERVAL,
    PUSH_ACTION_UPDATE,
    PUSH_UPDATE_INTERVAL,
    REFRESH_COOLDOWN,
    UPDATE_INTERVAL,
)
from .energy import EnergyStatistics
from .helpers import format_wd5, format_wd5_date, is_wd5
from .push import WD5PushClient

_LOGGER = logging.getLogger(__name__)


class OJMicrolineDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to fetch data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Class to manage fetching OJ Microline data.

        Args:
        ----
            hass: The HomeAssistant instance.
            entry: The ConfigEntry containing the user input.

        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFRESH_COOLDOWN, immediate=True
            ),
        )
        model_api = api_from_config_entry_data(entry.data)
        self._model_api = model_api
        self._energy_updated: float | None = None
        self.wd5_api: WD5API | None = (
            model_api if isinstance(model_api, WD5API) else None
        )
        self.api = oj_microline_from_api(model_api, hass)
        self.energy = EnergyStatistics(hass, self)

    async def _async_update_data(self) -> dict[str, Thermostat]:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.

        Returns
        -------
            An object containing the serial number as a key, and
            the resource as a value.

        Raises
        ------
            ConfigEntryAuthFailed: An invalid config was ued.
            UpdateFailed: An error occurred when updating the data.

        """
        try:
            async with async_timeout.timeout(API_TIMEOUT):
                thermostats = await self._async_fetch_thermostats()
                return {resource.serial_number: resource for resource in thermostats}

        except OJMicrolineAuthError as error:
            raise ConfigEntryAuthFailed from error

        except OJMicrolineError as error:
            raise UpdateFailed(error) from error

    async def _async_fetch_thermostats(self) -> list[Thermostat]:
        """Fetch the thermostats, reusing recent energy usage where possible.

        The library fetches energy usage for every thermostat on every poll,
        which is one extra request per thermostat. Energy usage changes
        slowly, so only refresh it every ENERGY_UPDATE_INTERVAL.
        """
        api = self._model_api
        if not isinstance(api, SessionOJMicrolineAPI):
            return await self.api.get_thermostats()

        await self.api.login()
        data = await api.request(
            api.get_thermostats_path,
            method="GET",
            params={
                # pylint: disable-next=protected-access
                "sessionid": api._session_id,  # noqa: SLF001
                **api.get_thermostats_params(),
            },
        )
        thermostats = api.parse_thermostats_response(data)

        now = monotonic()
        refresh_energy = (
            self._energy_updated is None
            or now - self._energy_updated >= ENERGY_UPDATE_INTERVAL
        )
        for thermostat in thermostats:
            previous = (self.data or {}).get(thermostat.serial_number)
            if not refresh_energy and previous is not None:
                thermostat.energy = previous.energy
            elif is_wd5(thermostat):
                # Today's usage per local hour; the library's own request uses
                # the UTC date, so it shows yesterday's total until 02:00.
                today = await self.energy.async_today(thermostat)
                thermostat.energy = [round(sum(today), 4)]
                self.energy.schedule_import(thermostat, today)
            else:
                thermostat.energy = await api.get_energy_usage(thermostat)
        if refresh_energy:
            self._energy_updated = now
        return thermostats

    def async_start_push(self, entry: ConfigEntry) -> None:
        """Start receiving push updates (WD5 series only)."""
        if self.wd5_api is None:
            return
        WD5PushClient(
            self.hass,
            async_get_clientsession(self.hass),
            self.wd5_api,
            self._async_handle_push_message,
            self._async_handle_push_connection,
        ).start(entry)

    @callback
    def _async_handle_push_connection(self, connected: bool) -> None:  # noqa: FBT001
        # Polling is still needed for energy usage and as a fallback, but
        # can be much less frequent while push updates are coming in.
        seconds = PUSH_UPDATE_INTERVAL if connected else UPDATE_INTERVAL
        # pylint: disable-next=attribute-defined-outside-init
        self.update_interval = timedelta(seconds=seconds)
        if connected:
            # Catch up on anything missed while disconnected.
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _async_handle_push_message(self, message: dict[str, Any]) -> None:
        _LOGGER.debug(
            "Push message received: %s",
            {
                key: len(value)
                for key, value in message.items()
                if isinstance(value, list)
            },
        )
        # "data" is defined by DataUpdateCoordinator, which pylint cannot see.
        # pylint: disable=access-member-before-definition
        if not self.data:
            return

        data = dict(self.data)
        # pylint: enable=access-member-before-definition
        changed = False
        # Group changes (mode, setpoints, schedule) apply to every thermostat
        # in the group; fetch everything again rather than guessing.
        needs_refresh = bool(message.get("Groups"))

        for item in message.get("ThermostatRealTimes") or []:
            current = data.get(item.get("SerialNumber"))
            if current is None:
                continue
            data[current.serial_number] = replace(
                current,
                online=item.get("Online", current.online),
                heating=item.get("Heating", current.heating),
                temperature_room=item.get("RoomTemperature", current.temperature_room),
                temperature_floor=item.get(
                    "FloorTemperature", current.temperature_floor
                ),
                sensor_mode=item.get("SensorAppl", current.sensor_mode),
            )
            changed = True

        for item in message.get("Thermostats") or []:
            current = data.get(item.get("SerialNumber"))
            if current is None or item.get("Action") != PUSH_ACTION_UPDATE:
                # Added or removed thermostat.
                needs_refresh = True
                continue
            try:
                thermostat = Thermostat.from_wd5_json(item)
            except (KeyError, TypeError, ValueError):
                needs_refresh = True
                continue
            thermostat.energy = current.energy
            data[current.serial_number] = thermostat
            changed = True

        if changed:
            # Unlike async_set_updated_data this keeps the polling schedule,
            # so energy usage keeps being refreshed.
            self.data = data  # pylint: disable=attribute-defined-outside-init
            self.async_update_listeners()
        if needs_refresh:
            self.hass.async_create_task(self.async_request_refresh())

    async def async_set_vacation(
        self,
        thermostat: Thermostat,
        start: date,
        end: date,
        *,
        enabled: bool,
    ) -> None:
        """Set the vacation period of a thermostat's group, and enable or disable it.

        Mirrors the vacation screen of the OJ Microline and SWATT apps: the
        vacation runs from 00:00 on the start date until 00:00 on the end date.
        If an enabled vacation has already begun, vacation mode is activated
        right away. When vacation mode is left (disabled, or moved to the
        future), the thermostat returns to schedule or manual mode, whichever
        was used last.

        Args:
        ----
            thermostat: The thermostat whose group to update.
            start: The first day of the vacation.
            end: The day normal regulation resumes.
            enabled: Whether the vacation is enabled.

        Raises:
        ------
            OJMicrolineError: The API refused the update.

        """
        regulation_mode = thermostat.regulation_mode
        if enabled and dt_util.start_of_local_day(start) <= dt_util.now():
            regulation_mode = REGULATION_VACATION
        elif regulation_mode == REGULATION_VACATION:
            regulation_mode = (
                REGULATION_SCHEDULE
                if thermostat.last_primary_mode_is_auto
                else REGULATION_MANUAL
            )

        await self._async_update_group(
            thermostat,
            {
                "RegulationMode": regulation_mode,
                "VacationEnabled": enabled,
                "VacationBeginDay": format_wd5_date(start),
                "VacationEndDay": format_wd5_date(end),
            },
        )

    async def async_change_vacation(
        self,
        thermostat: Thermostat,
        start: date,
        end: date,
        *,
        enabled: bool,
    ) -> None:
        """Validate and apply a vacation change requested by the user.

        Raises
        ------
            ServiceValidationError: The dates are not valid.
            HomeAssistantError: The API refused the update.

        """
        if self.wd5_api is None:
            msg = "Vacation can only be set on WD5-series thermostats."
            raise ServiceValidationError(msg)
        if end <= start:
            msg = "The vacation end date must be after the start date."
            raise ServiceValidationError(msg)
        if enabled and end <= dt_util.now().date():
            msg = "The vacation end date must be in the future."
            raise ServiceValidationError(msg)
        try:
            await self.async_set_vacation(thermostat, start, end, enabled=enabled)
        except OJMicrolineError as error:
            raise HomeAssistantError(str(error)) from error
        await self.async_request_delayed_refresh()

    async def async_change_schedule(
        self, thermostat: Thermostat, schedule: dict[str, Any]
    ) -> None:
        """Apply a schedule change requested by the user.

        Raises
        ------
            ServiceValidationError: The thermostat has no schedule.
            HomeAssistantError: The API refused the update.

        """
        if self.wd5_api is None:
            msg = "The schedule can only be set on WD5-series thermostats."
            raise ServiceValidationError(msg)
        try:
            await self.async_set_schedule(thermostat, schedule)
        except OJMicrolineError as error:
            raise HomeAssistantError(str(error)) from error
        await self.async_request_delayed_refresh()

    async def async_request_delayed_refresh(self) -> None:
        """Refresh shortly after a change; the API returns stale data right away.

        Push updates normally arrive first; this is the fallback.
        """
        await asyncio.sleep(2)
        await self.async_request_refresh()

    async def async_set_schedule(
        self, thermostat: Thermostat, schedule: dict[str, Any]
    ) -> None:
        """Set the weekly schedule of a thermostat's group.

        Raises
        ------
            OJMicrolineError: The API refused the update.

        """
        await self._async_update_group(
            thermostat, {"Schedule": schedule}, exclude_vacation=True
        )

    async def async_fetch_energy(
        self, thermostat: Thermostat, view_type: int, day: date, history: int
    ) -> Any:
        """Fetch the raw energy usage response (WD5 series only).

        Args:
        ----
            thermostat: The thermostat.
            view_type: The API's view type (2 = days, 4 = months in the apps).
            day: The reference date sent to the API.
            history: The API's history parameter.

        """
        api = self.wd5_api
        if api is None:
            msg = "Energy usage history is only supported on WD5-series thermostats."
            raise OJMicrolineError(msg)
        await self.api.login()
        return await api.request(
            api.get_energy_usage_path,
            method="POST",
            # pylint: disable-next=protected-access
            params={"sessionid": api._session_id},  # noqa: SLF001
            body={
                **api.get_thermostats_params(),
                "ThermostatID": thermostat.serial_number,
                "ViewType": view_type,
                "DateTime": day.isoformat(),
                "History": history,
            },
        )

    async def async_set_regulation_mode(
        self,
        thermostat: Thermostat,
        regulation_mode: int,
        temperature: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Set the regulation mode (preset) and optionally the temperature.

        Raises
        ------
            OJMicrolineError: The API refused the update.

        """
        duration = duration or COMFORT_DURATION
        if self.wd5_api is None:
            await self.api.set_regulation_mode(
                thermostat, regulation_mode, temperature, duration
            )
            return
        await self._async_update_group(
            thermostat,
            regulation_mode=regulation_mode,
            temperature=temperature,
            duration=duration,
        )

    async def _async_update_group(  # noqa: PLR0913 # pylint: disable=too-many-arguments
        self,
        thermostat: Thermostat,
        changes: dict[str, Any] | None = None,
        *,
        regulation_mode: int | None = None,
        temperature: int | None = None,
        duration: int = COMFORT_DURATION,
        exclude_vacation: bool = False,
    ) -> None:
        """Update settings of a thermostat's group (WD5 series only).

        The API replaces all group settings at once, so the thermostat's current
        settings are sent along with the changes. Date/times are sent back as
        the wall clock times the API returned (see helpers.py), except for the
        comfort/boost end time when that mode is being set.
        """
        api = self.wd5_api
        if api is None:
            msg = "This is only supported on WD5-series thermostats."
            raise OJMicrolineError(msg)

        body = api.update_regulation_mode_body(
            thermostat,
            thermostat.regulation_mode if regulation_mode is None else regulation_mode,
            temperature,
            duration,
        )
        group = body["SetGroup"]
        group.update(
            ExcludeVacationData=exclude_vacation,
            VacationBeginDay=format_wd5(thermostat.vacation_begin_time),
            VacationEndDay=format_wd5(thermostat.vacation_end_time),
        )
        if regulation_mode != REGULATION_COMFORT:
            group["ComfortEndTime"] = format_wd5(thermostat.comfort_end_time)
        if regulation_mode != REGULATION_BOOST:
            group["BoostEndTime"] = format_wd5(thermostat.boost_end_time)
        group.update(changes or {})

        await self.api.login()
        response = await api.request(
            api.update_regulation_mode_path,
            method="POST",
            # pylint: disable-next=protected-access
            params={"sessionid": api._session_id},  # noqa: SLF001
            body=body,
        )
        if not api.parse_update_regulation_mode_response(response):
            msg = "Unable to update the thermostat group."
            raise OJMicrolineError(msg)
