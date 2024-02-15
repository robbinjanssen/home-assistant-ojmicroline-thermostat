"""Support for OJ Microline entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OJMicrolineDataUpdateCoordinator


class OJMicrolineEntity(CoordinatorEntity[OJMicrolineDataUpdateCoordinator], Entity):
    """Defines an OJ Microline Entity."""

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

    @property
    def device_info(self) -> dict[str, Any]:
        """Return information to link this entity with the correct device.

        Returns
        -------
            The device identifiers to make sure the entity is attached
            to the correct device.

        """
        return {"identifiers": {(DOMAIN, self.idx)}}
