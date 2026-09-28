"""OJMicroline Thermostat platform configuration."""

import logging
from datetime import timedelta

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
)

from .api import api_from_config_entry_data, oj_microline_from_api
from .const import API_TIMEOUT, DOMAIN, UPDATE_INTERVAL
from .helpers import format_wd5

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
        )
        model_api = api_from_config_entry_data(entry.data)
        self.wd5_api: WD5API | None = (
            model_api if isinstance(model_api, WD5API) else None
        )
        self.api = oj_microline_from_api(model_api, hass)

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
                thermostats = await self.api.get_thermostats()
                return {resource.serial_number: resource for resource in thermostats}

        except OJMicrolineAuthError as error:
            raise ConfigEntryAuthFailed from error

        except OJMicrolineError as error:
            raise UpdateFailed(error) from error

    async def async_set_regulation_mode(
        self,
        thermostat: Thermostat,
        regulation_mode: int,
        temperature: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Set the regulation mode (preset) and optionally the temperature.

        For WD5-series thermostats the update is sent here rather than by the
        library: the API replaces all group settings at once, and the library
        sends back the comfort/boost end times and vacation dates shifted by
        the time zone offset (see helpers.py), moving them an hour earlier on
        every change.

        Raises
        ------
            OJMicrolineError: The API refused the update.

        """
        duration = duration or COMFORT_DURATION
        api = self.wd5_api
        if api is None:
            await self.api.set_regulation_mode(
                thermostat, regulation_mode, temperature, duration
            )
            return

        body = api.update_regulation_mode_body(
            thermostat, regulation_mode, temperature, duration
        )
        group = body["SetGroup"]
        group["VacationBeginDay"] = format_wd5(thermostat.vacation_begin_time)
        group["VacationEndDay"] = format_wd5(thermostat.vacation_end_time)
        if regulation_mode != REGULATION_COMFORT:
            group["ComfortEndTime"] = format_wd5(thermostat.comfort_end_time)
        if regulation_mode != REGULATION_BOOST:
            group["BoostEndTime"] = format_wd5(thermostat.boost_end_time)

        await self.api.login()
        response = await api.request(
            api.update_regulation_mode_path,
            method="POST",
            # pylint: disable-next=protected-access
            params={"sessionid": api._session_id},  # noqa: SLF001
            body=body,
        )
        if not api.parse_update_regulation_mode_response(response):
            msg = "Unable to set preset mode."
            raise OJMicrolineError(msg)
