"""OJMicroline Thermostat platform configuration."""
import logging
from datetime import timedelta

from ojmicroline_thermostat import (
    OJMicroline,
    OJMicrolineException,
    OJMicrolineAuthException,
)

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_CUSTOMER_ID,
    API_TIMEOUT,
    UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class OJMicrolineDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to fetch data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Class to manage fetching OJ Microline data."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.api = OJMicroline(
            host=entry.data[CONF_HOST],
            api_key=entry.data[CONF_API_KEY],
            customer_id=entry.data[CONF_CUSTOMER_ID],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            session=async_create_clientsession(hass),
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            async with async_timeout.timeout(API_TIMEOUT):
                results = await self.api.get_thermostats()
                return {device.serial_number: device for device in results}

        except OJMicrolineAuthException as error:
            raise ConfigEntryAuthFailed from error

        except OJMicrolineException as error:
            raise UpdateFailed(error) from error
