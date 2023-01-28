"""Config flow to configure OJMicroline."""
from typing import Any, Optional

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from ojmicroline_thermostat import (
    OJMicroline,
    OJMicrolineAuthException,
    OJMicrolineConnectionException,
    OJMicrolineException,
    OJMicrolineTimeoutException,
)
from ojmicroline_thermostat.const import COMFORT_DURATION

from .const import (
    CONF_COMFORT_MODE_DURATION,
    CONF_CUSTOMER_ID,
    CONF_DEFAULT_CUSTOMER_ID,
    CONF_DEFAULT_HOST,
    CONF_USE_COMFORT_MODE,
    CONFIG_FLOW_VERSION,
    DOMAIN,
    INTEGRATION_NAME,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=CONF_DEFAULT_HOST): str,
        vol.Required(CONF_CUSTOMER_ID, default=CONF_DEFAULT_CUSTOMER_ID): int,
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class OJMicrolineFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle an OJ Microline config flow."""

    VERSION = CONFIG_FLOW_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """
        Get the options flow for this handler.

        Args:
            config_entry: The ConfigEntry instance.

        Returns:
            The created config flow.
        """
        return OJMicrolineOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None) -> Any:
        """
        Handle a flow initialized by the user.

        Args:
            user_input: The input received from the user or none.

        Returns:
            The created config entry or a form to re-enter the user input with errors.
        """
        errors = {}
        if user_input:
            try:
                host = user_input[CONF_HOST]
                username = user_input[CONF_USERNAME]
                customer_id = user_input[CONF_CUSTOMER_ID]
                self._async_abort_entries_match(
                    {
                        CONF_HOST: host,
                        CONF_USERNAME: username,
                        CONF_CUSTOMER_ID: customer_id,
                    }
                )

                api = OJMicroline(
                    host=host,
                    api_key=user_input[CONF_API_KEY],
                    customer_id=customer_id,
                    username=username,
                    password=user_input[CONF_PASSWORD],
                    session=async_create_clientsession(self.hass),
                )
                await api.login()
            except OJMicrolineAuthException:
                errors["base"] = "invalid_auth"
            except OJMicrolineTimeoutException:
                errors["base"] = "timeout"
            except OJMicrolineConnectionException:
                errors["base"] = "connection_failed"
            except OJMicrolineException:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"{INTEGRATION_NAME} ({username})", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class OJMicrolineOptionsFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """
        Initialize options flow.

        Args:
            config_entry: The ConfigEntry instance.
        """
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Handle a flow initialized by the user.

        Args:
            user_input: The input received from the user or none.

        Returns:
            The created config entry.
        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_USE_COMFORT_MODE,
                        default=self.config_entry.options.get(
                            CONF_USE_COMFORT_MODE, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_COMFORT_MODE_DURATION,
                        default=self.config_entry.options.get(
                            CONF_COMFORT_MODE_DURATION, COMFORT_DURATION
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                }
            ),
        )
