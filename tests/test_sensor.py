"""Tests for the OJ Microline Thermostat sensors."""

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from ojmicroline_thermostat import OJMicrolineError

from .conftest import WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


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


async def test_unavailable_when_update_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test sensors become unavailable when updating the data fails."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_wg4_api.clear_requests()
    mock_wg4_api.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"SessionId": "f00b4r", "ErrorCode": 0},
        headers={"Content-Type": "application/json"},
    )
    mock_wg4_api.get(f"{WG4_HOST}/api/thermostats", status=500)
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.roomname_temperature_set_point")
    assert state is not None
    assert state.state == "unavailable"


@pytest.mark.usefixtures("mock_wg4_api")
async def test_energy_unknown_when_first_request_fails(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the energy usage is unknown, not 0 kWh (a meter reset), until fetched."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ojmicroline_thermostat.energy.EnergyStatistics.async_today",
        side_effect=OJMicrolineError("Unable to get energy usage via API."),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.roomname_energy_usage")
    assert state is not None
    assert state.state == "unknown"
