"""OJMicroline Thermostat platform configuration."""
import logging
from datetime import timedelta

from ojmicroline_thermostat import (
    OJMicroline,
    OJMicrolineConnectionError,
    OJMicrolineError,
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
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_CUSTOMER_ID,
    API_TIMEOUT,
    DEBOUNCE_COOLDOWN,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = 60


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OJMicroline as config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = OJMicrolineDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class OJMicrolineDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to fetch datas."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Class to manage fetching OJ Microline data."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=DEBOUNCE_COOLDOWN,
                immediate=False
            ),
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
        """Update data."""
        try:
            async with async_timeout.timeout(API_TIMEOUT):
                results = await self.api.get_thermostats()
                return {device.serial_number: device for device in results}

        except OJMicrolineConnectionError as error:
            raise ConfigEntryAuthFailed from error

        except OJMicrolineError as error:
            raise UpdateFailed(error) from error
