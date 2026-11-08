"""Energy price for WG4-series thermostats."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.exceptions import HomeAssistantError

from ojmicroline_thermostat import OJMicrolineError

from .models import OJMicrolineEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OJMicrolineConfigEntry, OJMicrolineDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OJMicrolineConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the energy price of thermostats that have one."""
    coordinator = entry.runtime_data
    async_add_entities(
        OJMicrolineEnergyPrice(coordinator, idx, hass.config.currency)
        for idx, thermostat in coordinator.data.items()
        if thermostat.energy_price is not None
    )


class OJMicrolineEnergyPrice(OJMicrolineEntity, NumberEntity):
    """The price per kWh that the app uses to show the energy costs.

    The cloud applies a new price to all stored usage, including earlier
    days, so it is disabled by default and not meant for changing tariffs.
    """

    _attr_translation_key = "energy_price"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 1000
    # The cloud accepts more decimals, but the thermostat truncates the
    # price to two at its next sync (#476).
    _attr_native_step = 0.01

    def __init__(
        self, coordinator: OJMicrolineDataUpdateCoordinator, idx: str, currency: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, idx)
        self._attr_unique_id = f"{idx}_energy_price"
        self._attr_native_unit_of_measurement = (
            f"{currency}/{UnitOfEnergy.KILO_WATT_HOUR}"
        )

    @property
    def native_value(self) -> float | None:
        """Return the price per kWh."""
        return self.thermostat.energy_price

    async def async_set_native_value(self, value: float) -> None:
        """Set the price per kWh and show it right away."""
        try:
            await self.coordinator.async_set_energy_price(self.thermostat, value)
        except OJMicrolineError as error:
            raise HomeAssistantError(str(error)) from error
