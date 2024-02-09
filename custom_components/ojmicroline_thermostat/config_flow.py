"""Config flow to configure OJMicroline."""
from typing import Any, Optional

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from ojmicroline_thermostat import (
    OJMicrolineAuthError,
    OJMicrolineConnectionError,
    OJMicrolineError,
    OJMicrolineTimeoutError,
)
from ojmicroline_thermostat.const import COMFORT_DURATION

from .api import oj_microline_from_config_entry_data
from .const import (
    CONF_COMFORT_MODE_DURATION,
    CONF_CUSTOMER_ID,
    CONF_MODEL,
    CONF_USE_COMFORT_MODE,
    CONFIG_FLOW_VERSION,
    DOMAIN,
    INTEGRATION_NAME,
    MODEL_WD5_SERIES,
    MODEL_WG4_SERIES,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODEL): vol.In([MODEL_WD5_SERIES, MODEL_WG4_SERIES]),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        CONF_HOST: str,
        CONF_CUSTOMER_ID: int,
        CONF_API_KEY: str,
    }
)

USER_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODEL): vol.In([MODEL_WD5_SERIES, MODEL_WG4_SERIES]),
    }
)

WD5_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_API_KEY): str,
        CONF_HOST: str,
        CONF_CUSTOMER_ID: int,
    }
)

WG4_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        CONF_HOST: str,
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
        if user_input:
            if user_input[CONF_MODEL] == MODEL_WD5_SERIES:
                return await self.async_step_wd5()
            return await self.async_step_wg4()
        return self.async_show_form(
            step_id="user",
            data_schema=USER_STEP_SCHEMA,
        )

    async def async_step_wg4(self, user_input: Optional[dict[str, Any]] = None) -> Any:
        """
        Step that gathers information for WG4-series thermostats, creating a
        config entry if successful.

        Args:
            user_input: The input received from the user or none.

        Returns:
            The created config entry or a form to re-enter the user input with errors.
        """
        errors: dict[str, str] = {}
        if user_input:
            result = await self._async_try_create_entry(
                {
                    CONF_MODEL: MODEL_WG4_SERIES,
                    **user_input,
                },
                errors,
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="wg4", data_schema=WG4_STEP_SCHEMA, errors=errors
        )

    async def async_step_wd5(self, user_input: Optional[dict[str, Any]] = None) -> Any:
        """
        Step that gathers information for WD5-series thermostats, creating a
        config entry if successful.

        Args:
            user_input: The input received from the user or none.

        Returns:
            The created config entry or a form to re-enter the user input with errors.
        """
        errors: dict[str, str] = {}
        if user_input:
            result = await self._async_try_create_entry(
                {
                    CONF_MODEL: MODEL_WD5_SERIES,
                    **user_input,
                },
                errors,
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="wd5", data_schema=WD5_STEP_SCHEMA, errors=errors
        )

    async def _async_try_create_entry(
        self, data: dict[str, Any], errors: dict[str, str]
    ) -> Optional[FlowResult]:
        """
        Validates the config entry data and logs in to the API.
        If successful, calls async_create_entry and returns the FlowResult.
        Otherwise, stores an error in the errors dict and returns None.
        """
        data = DATA_SCHEMA(data)
        try:
            # Disallow duplicate entries...
            self._async_abort_entries_match(
                {
                    k: data[k]
                    for k in data
                    # ... only considering model/host/username as
                    # distinguishing keys.
                    if k in [CONF_MODEL, CONF_HOST, CONF_USERNAME]
                }
            )
            api = oj_microline_from_config_entry_data(data, self.hass)
            await api.login()
        except OJMicrolineAuthError:
            errors["base"] = "invalid_auth"
        except OJMicrolineTimeoutError:
            errors["base"] = "timeout"
        except OJMicrolineConnectionError:
            errors["base"] = "connection_failed"
        except OJMicrolineError:
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=f"{INTEGRATION_NAME} ({data[CONF_USERNAME]})", data=data
            )
        return None


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
