"""OJMicroline Thermostat platform configuration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import OJMicrolineDataUpdateCoordinator

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up OJMicroline as config entry.

    Args:
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.

    Returns:
        Return true after setting up.
    """
    hass.data.setdefault(DOMAIN, {})

    coordinator = OJMicrolineDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry.

    Args:
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.

    Returns:
        Return true if unload was successful, false otherwise.
    """
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
