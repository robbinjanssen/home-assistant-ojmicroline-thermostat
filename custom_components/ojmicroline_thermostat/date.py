"""Vacation dates for WD5-series thermostats."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.date import DateEntity

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
    """Set up the vacation begin and end dates."""
    coordinator: OJMicrolineDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        OJMicrolineVacationDate(coordinator, idx, end=end)
        for idx, thermostat in coordinator.data.items()
        if is_wd5(thermostat)
        for end in (False, True)
    )


class OJMicrolineVacationDate(OJMicrolineEntity, DateEntity):
    """The first day of the vacation, or the day normal regulation resumes.

    Like in the apps, the dates belong to the thermostat's group. Changing a
    date keeps the vacation enabled or disabled; moving one date past the other
    moves the other along, keeping at least one day in between.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OJMicrolineDataUpdateCoordinator,
        idx: str,
        *,
        end: bool,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, idx)
        self._end = end
        self._attr_translation_key = "vacation_end" if end else "vacation_begin"
        self._attr_icon = "mdi:calendar-end" if end else "mdi:calendar-start"
        self._attr_unique_id = f"{idx}_{self._attr_translation_key}"

    @property
    def native_value(self) -> date | None:
        """Return the date."""
        thermostat = self.coordinator.data[self.idx]
        return wd5_date(
            thermostat.vacation_end_time
            if self._end
            else thermostat.vacation_begin_time
        )

    async def async_set_value(self, value: date) -> None:
        """Change the date."""
        thermostat = self.coordinator.data[self.idx]
        start = wd5_date(thermostat.vacation_begin_time)
        end = wd5_date(thermostat.vacation_end_time)
        if self._end:
            end = value
            if start is None or start >= end:
                start = end - timedelta(days=1)
        else:
            start = value
            if end is None or end <= start:
                end = start + timedelta(days=1)
        await self.coordinator.async_change_vacation(
            thermostat, start, end, enabled=bool(thermostat.vacation_mode)
        )
