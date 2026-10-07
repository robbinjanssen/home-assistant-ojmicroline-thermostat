"""Tests for the OJ Microline Thermostat sensors."""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.mark.usefixtures("mock_wg4_api")
@pytest.mark.parametrize(
    ("entity_id", "name", "state"),
    [
        ("sensor.roomname_power", "RoomName Power", "0.0"),
        ("sensor.roomname_energy_usage", "RoomName Energy usage", "59.3"),
        (
            "sensor.roomname_temperature_set_point",
            "RoomName Temperature set point",
            "26.0",
        ),
        ("binary_sensor.roomname_online", "RoomName Online", "on"),
        ("binary_sensor.secondroom_heating", "SecondRoom Heating", "off"),
    ],
)
async def test_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_id: str,
    name: str,
    state: str,
) -> None:
    """Test translated entity names keep the entity IDs of earlier versions."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    assert entity_state.name == name
    assert entity_state.state == state
