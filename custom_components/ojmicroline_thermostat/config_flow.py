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
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
from ojmicroline_thermostat.ojmicroline import SessionOJMicrolineAPI

from .api import (
    api_from_config_entry_data,
    async_fetch_thermostats,
    oj_microline_from_api,
)
from .const import (
    APP_OTHER,
    CONF_APP,
    CONF_APPLICATION,
    CONF_COMFORT_MODE_DURATION,
    CONF_COMFORT_TEMPERATURE,
    CONF_CONNECTION_MODE,
    CONF_CUSTOMER_ID,
    CONF_IDENTITY_HOST,
    CONF_MODEL,
    CONF_USE_COMFORT_MODE,
    CONFIG_FLOW_VERSION,
    CONNECTION_CLOUD,
    CONNECTION_LOCAL,
    CONNECTION_MODES,
    DEFAULT_WG4_APPLICATION,
    DOMAIN,
    INTEGRATION_NAME,
    MODEL_WD5_SERIES,
    MODEL_WG4_SERIES,
    MODEL_WG5_SERIES,
    WD5_APPS,
    WG4_APPS,
)
from .local import (
    ENDPOINT,
    async_dns_points_here,
    async_has_profile,
    async_host_ip,
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
        CONF_IDENTITY_HOST: str,
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
        probatio.Optional(CONF_IDENTITY_HOST): str,
    }
)


def _app_step_schema(apps: Mapping[str, Any]) -> probatio.Schema:
    """Return the schema of the step that asks which app is used."""
    return probatio.Schema(
        {
            probatio.Required(CONF_APP, default=APP_OTHER): SelectSelector(
                SelectSelectorConfig(
                    options=[*apps, APP_OTHER],
                    translation_key=CONF_APP,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
    )


WD5_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
        probatio.Optional(CONF_API_KEY): str,
        probatio.Optional(CONF_HOST): str,
        probatio.Optional(CONF_CUSTOMER_ID): int,
    }
)

WG4_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
        probatio.Optional(CONF_HOST): str,
        probatio.Optional(CONF_APPLICATION, default=DEFAULT_WG4_APPLICATION): int,
    }
)


STEP_SCHEMAS = {
    MODEL_WD5_SERIES: WD5_STEP_SCHEMA,
    MODEL_WG4_SERIES: WG4_STEP_SCHEMA,
    MODEL_WG5_SERIES: WG5_STEP_SCHEMA,
}

# The keys that distinguish one account from another.
ACCOUNT_KEYS = (CONF_MODEL, CONF_HOST, CONF_USERNAME)


class OJMicrolineFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle an OJ Microline config flow."""

    VERSION = CONFIG_FLOW_VERSION
    # The app chosen in the wd5_app or wg4_app step, whose settings fill in
    # the form of the series.
    _app = APP_OTHER

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
                return await self.async_step_wd5_app()
            if user_input[CONF_MODEL] == MODEL_WG5_SERIES:
                return await self.async_step_wg5()
            return await self.async_step_wg4_app()
        return self.async_show_form(
            step_id="user",
            data_schema=USER_STEP_SCHEMA,
        )

    async def async_step_wg4_app(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step that asks which app is used for WG4-series thermostats.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The WG4 form, filled in with the app's settings, or the app form.

        """
        if user_input:
            self._app = user_input[CONF_APP]
            return await self.async_step_wg4()
        return self.async_show_form(
            step_id="wg4_app", data_schema=_app_step_schema(WG4_APPS)
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
            step_id="wg4",
            data_schema=self.add_suggested_values_to_schema(
                WG4_STEP_SCHEMA, user_input or WG4_APPS.get(self._app, {})
            ),
            errors=errors,
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

    async def async_step_wd5_app(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step that asks which app is used for WD5-series thermostats.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The WD5 form, filled in with the app's settings, or the app form.

        """
        if user_input:
            self._app = user_input[CONF_APP]
            return await self.async_step_wd5()
        return self.async_show_form(
            step_id="wd5_app", data_schema=_app_step_schema(WD5_APPS)
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
            step_id="wd5",
            data_schema=self.add_suggested_values_to_schema(
                WD5_STEP_SCHEMA, user_input or WD5_APPS.get(self._app, {})
            ),
            errors=errors,
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
        self._async_abort_entries_match({k: data[k] for k in data if k in ACCOUNT_KEYS})
        if (
            error := await self._async_validate_login(data, check_thermostats=True)
        ) is not None:
            errors["base"] = error
            return None
        return self.async_create_entry(
            title=f"{INTEGRATION_NAME} ({data[CONF_USERNAME]})", data=data
        )

    async def _async_validate_login(
        self, data: Mapping[str, Any], *, check_thermostats: bool = False
    ) -> str | None:
        """Log in to the API with the given config entry data.

        Args:
        ----
            data: The config entry data.
            check_thermostats: Whether the account must have thermostats. With
                the wrong application code (WG4 series), the login succeeds
                but the account looks empty.

        Returns:
        -------
            None if the login succeeded, otherwise the error key.

        """
        try:
            model_api = api_from_config_entry_data(data)
            await oj_microline_from_api(model_api, self.hass).login()
            if (
                check_thermostats
                and isinstance(model_api, SessionOJMicrolineAPI)
                and not await async_fetch_thermostats(model_api)
            ):
                return "no_thermostats"
        except OJMicrolineAuthError:
            return "invalid_auth"
        except OJMicrolineTimeoutError:
            return "timeout"
        except OJMicrolineConnectionError:
            return "connection_failed"
        except OJMicrolineError:
            return "unknown"
        return None

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the account settings of an existing entry.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            An abort result after updating the entry or a form with errors.

        """
        entry = self._get_reconfigure_entry()
        model = entry.data[CONF_MODEL]
        errors: dict[str, str] = {}
        if user_input is not None:
            # Optional fields that were cleared are left out, so their
            # defaults apply again.
            data = DATA_SCHEMA({CONF_MODEL: model, **user_input})
            account = {k: data.get(k) for k in ACCOUNT_KEYS}
            for other in self._async_current_entries(include_ignore=False):
                if other.entry_id != entry.entry_id and account == {
                    k: other.data.get(k) for k in ACCOUNT_KEYS
                }:
                    return self.async_abort(reason="already_configured")
            if (
                error := await self._async_validate_login(data, check_thermostats=True)
            ) is None:
                return self.async_update_reload_and_abort(
                    entry,
                    title=f"{INTEGRATION_NAME} ({data[CONF_USERNAME]})",
                    data=data,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_SCHEMAS[model], user_input or entry.data
            ),
            errors=errors,
        )

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

    def __init__(self) -> None:
        """Start without chosen options, and without a warning shown."""
        self._options: dict[str, Any] = {}
        # A warning about the DNS record is shown once; submitting again goes on.
        self._warned = False

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The created config entry, or the next form.

        """
        errors: dict[str, str] = {}
        options = self.config_entry.options
        current_mode = options.get(CONF_CONNECTION_MODE, CONNECTION_CLOUD)
        if user_input is not None:
            self._options = user_input
            if (
                user_input.get(CONF_CONNECTION_MODE, CONNECTION_CLOUD)
                != CONNECTION_CLOUD
            ):
                return await self.async_step_gateway()
            if (
                current_mode != CONNECTION_CLOUD
                and not self._warned
                and await async_dns_points_here(
                    self.hass, await async_host_ip(self.hass)
                )
            ):
                # Left in place, the DNS record keeps the thermostats away
                # from the cloud.
                self._warned = True
                errors["base"] = "dns_still_local"
            else:
                return self.async_create_entry(title="", data=user_input)

        # What was just entered comes back when the form is shown again.
        values = {**options, **self._options}
        schema: dict[Any, Any] = {
            probatio.Optional(
                CONF_USE_COMFORT_MODE,
                default=values.get(CONF_USE_COMFORT_MODE, False),
            ): bool,
            probatio.Optional(
                CONF_COMFORT_MODE_DURATION,
                default=values.get(CONF_COMFORT_MODE_DURATION, COMFORT_DURATION),
            ): probatio.All(probatio.Coerce(int), probatio.Range(min=1)),
            # Empty: use the comfort temperature stored in the thermostat.
            probatio.Optional(
                CONF_COMFORT_TEMPERATURE,
                description={"suggested_value": values.get(CONF_COMFORT_TEMPERATURE)},
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5,
                    max=40,
                    step=0.5,
                    unit_of_measurement=UnitOfTemperature.CELSIUS,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
        if self.config_entry.data.get(CONF_MODEL) == MODEL_WG4_SERIES:
            # Only WG4-series thermostats can connect to a local gateway.
            schema[
                probatio.Required(
                    CONF_CONNECTION_MODE,
                    default=values.get(CONF_CONNECTION_MODE, CONNECTION_CLOUD),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=CONNECTION_MODES,
                    translation_key=CONF_CONNECTION_MODE,
                    mode=SelectSelectorMode.LIST,
                )
            )
        return self.async_show_form(
            step_id="init", data_schema=probatio.Schema(schema), errors=errors
        )

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the DNS record a local connection needs, and check for it.

        Args:
        ----
            user_input: Empty once the user confirmed, or none.

        Returns:
        -------
            The created config entry, or the form with what is missing.

        """
        errors: dict[str, str] = {}
        host_ip = await async_host_ip(self.hass)
        if user_input is not None:
            if self._options[
                CONF_CONNECTION_MODE
            ] == CONNECTION_LOCAL and not await async_has_profile(
                self.hass, self.config_entry
            ):
                # Without a relayed session there is nothing to answer a
                # thermostat with.
                errors["base"] = "no_profile"
            elif not self._warned and not await async_dns_points_here(
                self.hass, host_ip
            ):
                # The thermostats may use another DNS server than Home
                # Assistant does, so this only warns.
                self._warned = True
                errors["base"] = "dns_not_detected"
            else:
                return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="gateway",
            data_schema=probatio.Schema({}),
            errors=errors,
            description_placeholders={
                "hostname": ENDPOINT.host,
                "ip": host_ip,
                "port": str(ENDPOINT.port),
            },
        )
