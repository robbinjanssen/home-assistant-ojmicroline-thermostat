"""OJMicroline Thermostat platform configuration."""

import logging
from datetime import timedelta

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ojmicroline_thermostat import OJMicrolineAuthError, OJMicrolineError, Thermostat

from .api import oj_microline_from_config_entry_data
from .const import API_TIMEOUT, DOMAIN, UPDATE_INTERVAL

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
        self.api = oj_microline_from_config_entry_data(entry.data, hass)

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
