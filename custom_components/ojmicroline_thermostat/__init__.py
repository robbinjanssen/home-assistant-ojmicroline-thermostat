"""OJMicroline Thermostat platform configuration."""

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CONF_MODEL, CONFIG_FLOW_VERSION, DOMAIN, MODEL_WD5_SERIES
from .coordinator import OJMicrolineDataUpdateCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = f"/{DOMAIN}/ojmicroline-schedule-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "ojmicroline-schedule-card.js"

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DATE,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Serve the bundled schedule card and load it in the frontend.

    Args:
    ----
        hass: The HomeAssistant instance.
        config: The configuration (unused; the integration is UI-only).

    Returns:
    -------
        Return true after setting up.

    """
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    # The version busts browser caches after an update.
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OJMicroline as config entry.

    Args:
    ----
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.

    Returns:
    -------
        Return true after setting up.

    """
    hass.data.setdefault(DOMAIN, {})

    coordinator = OJMicrolineDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start_push(entry)

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
    ----
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.

    Returns:
    -------
        Return true if unload was successful, false otherwise.

    """
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries from previous versions."""
    if config_entry.version > CONFIG_FLOW_VERSION:
        return False  # Downgrade from future version

    if config_entry.version == 1:
        # Version 1 only supported WD5; version 2 requires CONF_MODEL
        config_entry.version = CONFIG_FLOW_VERSION
        hass.config_entries.async_update_entry(
            config_entry,
            data={
                CONF_MODEL: MODEL_WD5_SERIES,
                **config_entry.data,
            },
        )

    return True
