"""Helper to construct OJMicroline objects."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from ojmicroline_thermostat import OJMicroline, WD5API, WG4API

from .const import (
    CONF_MODEL,
    CONF_CUSTOMER_ID,
    MODEL_WD5_SERIES,
    MODEL_WG4_SERIES,
)


def oj_microline_from_config_entry_data(
    data: dict[str, Any], hass: HomeAssistant
) -> OJMicroline:
    """
    Constructs an OJMicroline object from the given config entry data.
    """
    return OJMicroline(
        api=_api_from_config_entry_data(data),
        session=async_create_clientsession(hass),
    )


def _api_from_config_entry_data(data: dict[str, Any]) -> Any:
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
            **extra_args,
        )
    raise RuntimeError(f"Unknown model {model}")
