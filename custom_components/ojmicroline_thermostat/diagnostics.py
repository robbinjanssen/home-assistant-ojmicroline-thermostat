"""Diagnostics for OJ Microline thermostats."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME
from homeassistant.util import dt as dt_util

from ojmicroline_thermostat import OJMicrolineError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import (
        OJMicrolineConfigEntry,
        OJMicrolineDataUpdateCoordinator,
    )

TO_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME}

# (description, view type, days relative to today, history) as the apps and
# the library request energy usage; used to document the API's behavior.
ENERGY_PROBES = [
    ("days, today, history 0", 2, 0, 0),
    ("days, tomorrow, history 0 (library)", 2, 1, 0),
    ("days, today, history 4 (app month view)", 2, 0, 4),
    ("view type 1, today, history 0", 1, 0, 0),
    ("months, 11 months ago, history 0 (app year view)", 4, -334, 0),
]


def _gateway_diagnostics(
    coordinator: OJMicrolineDataUpdateCoordinator,
) -> dict[str, Any] | None:
    """Describe the local gateway, without the snapshot and profiles it stores.

    The history is what a report of a real thermostat needs: how its
    connection went, and every message by field number. It never holds a
    login, which has the email address of the account.
    """
    if (local := coordinator.local) is None:
        return None
    gateway = local.gateway
    status = gateway.upstream_status
    cloud_error = local.api.cloud_error
    return {
        "mode": local.mode.value,
        "connected": len(gateway.connected),
        "relayed": sum(gateway.is_relayed(serial) for serial in gateway.connected),
        "profiles": len(gateway.profiles),
        "upstream": None if status is None else status.value,
        "upstream_fingerprint": gateway.upstream_fingerprint,
        "cloud_error": None if cloud_error is None else repr(cloud_error),
        "history": list(gateway.history),
    }


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: OJMicrolineConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    today = dt_util.now().date()

    thermostats = {}
    for serial, thermostat in (coordinator.data or {}).items():
        info: dict[str, Any] = {"data": dataclasses.asdict(thermostat)}
        if coordinator.wd5_api is not None:
            energy = {}
            for description, view_type, days, history in ENERGY_PROBES:
                try:
                    energy[description] = await coordinator.async_fetch_energy(
                        thermostat, view_type, today + timedelta(days=days), history
                    )
                except OJMicrolineError as error:
                    energy[description] = f"error: {error}"
            info["energy_usage"] = energy
        thermostats[serial] = info

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "gateway": _gateway_diagnostics(coordinator),
        "today": today.isoformat(),
        "time_zone": str(dt_util.get_default_time_zone()),
        "thermostats": thermostats,
    }
