"""Support for OJ Microline entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OJMicrolineDataUpdateCoordinator

if TYPE_CHECKING:
    from ojmicroline_thermostat import Thermostat


class OJMicrolineEntity(CoordinatorEntity[OJMicrolineDataUpdateCoordinator], Entity):
    """Defines an OJ Microline Entity."""

    _attr_has_entity_name = True

    idx: str

    def __init__(self, coordinator: OJMicrolineDataUpdateCoordinator, idx: str) -> None:
        """Initialise the entity.

        Args:
        ----
            coordinator: The data coordinator updating the models.
            idx: The identifier for this entity.

        """
        super().__init__(coordinator)
        self.idx = idx
        self._thermostat: Thermostat = coordinator.data[idx]

    @property
    def thermostat(self) -> Thermostat:
        """Return the thermostat's data.

        A thermostat removed from the account keeps its last known data, so
        that the entity becomes unavailable instead of failing.
        """
        if (thermostat := self.coordinator.data.get(self.idx)) is not None:
            self._thermostat = thermostat
        return self._thermostat

    @property
    def available(self) -> bool:
        """Return whether the data is up to date and the thermostat still exists."""
        return super().available and self.idx in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device.

        Returns
        -------
            The device identifiers to make sure the entity is attached
            to the correct device.

        """
        return DeviceInfo(
            identifiers={(DOMAIN, self.idx)},
            name=self.thermostat.name,
        )
