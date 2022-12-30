"""Support for OJ Microline entities."""
from __future__ import annotations

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OJMicrolineDataUpdateCoordinator


class OJMicrolineEntity(CoordinatorEntity[OJMicrolineDataUpdateCoordinator], Entity):
    """Defines an OJ Microline Entity."""

    idx: str

    def __init__(self, coordinator: OJMicrolineDataUpdateCoordinator, idx: str) -> None:
        """Call parent init()"""
        super().__init__(coordinator)

        """Set the thermostat id"""
        self.idx = idx

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self.idx)}}
