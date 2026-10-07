"""Config flow to configure OJMicroline."""

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from ojmicroline_thermostat import (
    OJMicrolineAuthError,
    OJMicrolineConnectionError,
    OJMicrolineError,
    OJMicrolineTimeoutError,
)
from ojmicroline_thermostat.const import COMFORT_DURATION

from .api import oj_microline_from_config_entry_data
from .const import (
    CONF_APPLICATION,
    CONF_COMFORT_MODE_DURATION,
    CONF_CUSTOMER_ID,
    CONF_MODEL,
    CONF_USE_COMFORT_MODE,
    CONFIG_FLOW_VERSION,
    DEFAULT_WG4_APPLICATION,
    DOMAIN,
    INTEGRATION_NAME,
    MODEL_WD5_SERIES,
    MODEL_WG4_SERIES,
    MODEL_WG5_SERIES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_MODEL): probatio.In(
            [MODEL_WD5_SERIES, MODEL_WG4_SERIES, MODEL_WG5_SERIES]
        ),
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
        CONF_HOST: str,
        CONF_CUSTOMER_ID: int,
        CONF_API_KEY: str,
        probatio.Optional(CONF_APPLICATION): int,
    }
)

REAUTH_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

USER_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_MODEL): probatio.In(
            [MODEL_WD5_SERIES, MODEL_WG4_SERIES, MODEL_WG5_SERIES]
        ),
    }
)

WG5_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

WD5_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
        probatio.Required(CONF_API_KEY): str,
        CONF_HOST: str,
        CONF_CUSTOMER_ID: int,
    }
)

WG4_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
        CONF_HOST: str,
        probatio.Optional(CONF_APPLICATION, default=DEFAULT_WG4_APPLICATION): int,
    }
)


class OJMicrolineFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle an OJ Microline config flow."""

    VERSION = CONFIG_FLOW_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004 # pylint: disable=unused-argument
    ) -> OptionsFlow:
        """Get the options flow for this handler.

        Args:
        ----
            config_entry: The ConfigEntry instance.

        Returns:
        -------
            The created config flow.

        """
        return OJMicrolineOptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Handle a flow initialized by the user.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The created config entry or a form to re-enter the user input with errors.

        """
        if user_input:
            if user_input[CONF_MODEL] == MODEL_WD5_SERIES:
                return await self.async_step_wd5()
            if user_input[CONF_MODEL] == MODEL_WG5_SERIES:
                return await self.async_step_wg5()
            return await self.async_step_wg4()
        return self.async_show_form(
            step_id="user",
            data_schema=USER_STEP_SCHEMA,
        )

    async def async_step_wg4(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step that gathers information for WG4-series thermostats.

        The result is a config entry if successful.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
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

    async def async_step_wg5(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step that gathers information for WG5-series thermostats.

        The result is a config entry if successful.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The created config entry or a form to re-enter the user input with errors.

        """
        errors: dict[str, str] = {}
        if user_input:
            result = await self._async_try_create_entry(
                {
                    CONF_MODEL: MODEL_WG5_SERIES,
                    **user_input,
                },
                errors,
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="wg5", data_schema=WG5_STEP_SCHEMA, errors=errors
        )

    async def async_step_wd5(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step that gathers information for WD5-series thermostats.

        The result is a config entry if successful.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
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
    ) -> ConfigFlowResult | None:
        """Validate the config entry data and logs in to the API.

        If successful, calls async_create_entry and returns the ConfigFlowResult.
        Otherwise, stores an error in the errors dict and returns None.
        """
        data = DATA_SCHEMA(data)
        # Disallow duplicate entries, only considering model/host/username as
        # distinguishing keys.
        self._async_abort_entries_match(
            {k: data[k] for k in data if k in [CONF_MODEL, CONF_HOST, CONF_USERNAME]}
        )
        if (error := await self._async_validate_login(data)) is not None:
            errors["base"] = error
            return None
        return self.async_create_entry(
            title=f"{INTEGRATION_NAME} ({data[CONF_USERNAME]})", data=data
        )

    async def _async_validate_login(self, data: Mapping[str, Any]) -> str | None:
        """Log in to the API with the given config entry data.

        Returns
        -------
            None if the login succeeded, otherwise the error key.

        """
        try:
            api = oj_microline_from_config_entry_data(dict(data), self.hass)
            await api.login()
        except OJMicrolineAuthError:
            return "invalid_auth"
        except OJMicrolineTimeoutError:
            return "timeout"
        except OJMicrolineConnectionError:
            return "connection_failed"
        except OJMicrolineError:
            return "unknown"
        return None

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002 # pylint: disable=unused-argument
    ) -> ConfigFlowResult:
        """Handle a login that was rejected, for example after a password change.

        Args:
        ----
            entry_data: The data of the config entry.

        Returns:
        -------
            The form to enter the new password.

        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password and update the config entry.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            An abort result after updating the entry or a form with errors.

        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            if (error := await self._async_validate_login(data)) is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )


class OJMicrolineOptionsFlowHandler(OptionsFlowWithReload):
    """Handle options; the entry reloads so they apply right away."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The created config entry.

        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_USE_COMFORT_MODE,
                        default=self.config_entry.options.get(
                            CONF_USE_COMFORT_MODE, False
                        ),
                    ): bool,
                    probatio.Optional(
                        CONF_COMFORT_MODE_DURATION,
                        default=self.config_entry.options.get(
                            CONF_COMFORT_MODE_DURATION, COMFORT_DURATION
                        ),
                    ): probatio.All(probatio.Coerce(int), probatio.Range(min=1)),
                }
            ),
        )
