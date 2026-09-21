"""Vacation switch for WD5-series thermostats."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .helpers import is_wd5, wd5_date
from .models import OJMicrolineEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OJMicrolineDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the vacation switches."""
    coordinator: OJMicrolineDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        OJMicrolineVacationSwitch(coordinator, idx)
        for idx, thermostat in coordinator.data.items()
        if is_wd5(thermostat)
    )


class OJMicrolineVacationSwitch(OJMicrolineEntity, SwitchEntity):
    """Enables the vacation period set with the vacation date entities."""

    _attr_has_entity_name = True
    _attr_translation_key = "vacation"
    _attr_icon = "mdi:beach"

    def __init__(self, coordinator: OJMicrolineDataUpdateCoordinator, idx: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, idx)
        self._attr_unique_id = f"{idx}_vacation"

    @property
    def is_on(self) -> bool:
        """Return whether the vacation is enabled."""
        return bool(self.coordinator.data[self.idx].vacation_mode)

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Enable the vacation period."""
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable the vacation period."""
        await self._async_set(enabled=False)

    async def _async_set(self, *, enabled: bool) -> None:
        thermostat = self.coordinator.data[self.idx]
        start = wd5_date(thermostat.vacation_begin_time)
        end = wd5_date(thermostat.vacation_end_time)
        if start is None or end is None or (enabled and end <= dt_util.now().date()):
            msg = "Set the vacation dates first; the end date must be in the future."
            raise ServiceValidationError(msg)
        await self.coordinator.async_change_vacation(
            thermostat, start, end, enabled=enabled
        )
