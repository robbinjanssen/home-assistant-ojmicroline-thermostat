"""Helper to construct OJMicroline objects."""

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from ojmicroline_thermostat import WD5API, WG4API, WG5API, OJMicroline

from .const import (
    CONF_APPLICATION,
    CONF_CUSTOMER_ID,
    CONF_IDENTITY_HOST,
    CONF_MODEL,
    DEFAULT_WG4_APPLICATION,
    MODEL_WD5_SERIES,
    MODEL_WG4_SERIES,
    MODEL_WG5_SERIES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant


def oj_microline_from_config_entry_data(
    data: dict[str, Any], hass: HomeAssistant
) -> OJMicroline:
    """Construct an OJMicroline object from the given config entry data."""
    return oj_microline_from_api(api_from_config_entry_data(data), hass)


def oj_microline_from_api(api: Any, hass: HomeAssistant) -> OJMicroline:
    """Construct an OJMicroline object around an already created API object."""
    return OJMicroline(api=api, session=async_create_clientsession(hass))


def api_from_config_entry_data(data: Mapping[str, Any]) -> Any:
    """Construct the model-specific API object from the given config entry data."""
    # Only pass the host kwarg if it's overridden; otherwise
    # omit it to use the argument's default value.
    extra_args = {}
    if CONF_HOST in data:
        extra_args["host"] = data[CONF_HOST]

    model = data[CONF_MODEL]
    if model == MODEL_WD5_SERIES:
        return WD5API(
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            api_key=data[CONF_API_KEY],
            customer_id=data.get(CONF_CUSTOMER_ID, 99),
            **extra_args,
        )
    if model == MODEL_WG4_SERIES:
        return WG4API(
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            application=data.get(CONF_APPLICATION, DEFAULT_WG4_APPLICATION),
            **extra_args,
        )
    if model == MODEL_WG5_SERIES:
        wg5_args = dict(extra_args)
        # Optional OAuth2 identity server override (e.g. nJoy / WarmlyYours).
        # Blank or absent: the library default (identity.ojmicroline.com).
        if data.get(CONF_IDENTITY_HOST):
            wg5_args["identity_host"] = data[CONF_IDENTITY_HOST]
        return WG5API(
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            **wg5_args,
        )
    msg = f"Unknown model {model}"
    raise RuntimeError(msg)
