"""Config flow to configure OJMicroline."""
import logging

from .const import CONF_CUSTOMER_ID

import voluptuous as vol
from ojmicroline_thermostat import (
    OJMicroline,
    OJMicrolineConnectionError,
    OJMicrolineError,
)
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_CUSTOMER_ID): int
    }
)

_LOGGER = logging.getLogger(__name__)


class OJMicrolineFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a OJMicroline config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input:
            try:
                host = user_input[CONF_HOST]
                username = user_input[CONF_USERNAME]
                customer_id = user_input[CONF_CUSTOMER_ID]
                self._async_abort_entries_match({
                    CONF_HOST: host,
                    CONF_USERNAME: username,
                    CONF_CUSTOMER_ID: customer_id,
                })

                api = OJMicroline(
                    host=host,
                    api_key=user_input[CONF_API_KEY],
                    customer_id=customer_id,
                    username=username,
                    password=user_input[CONF_PASSWORD],
                    session=async_create_clientsession(self.hass),
                )
                await api.login()
            except OJMicrolineConnectionError:
                errors["base"] = "invalid_auth"
            except OJMicrolineError:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"{DOMAIN} ({host, username, customer_id})",
                    data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors
        )
