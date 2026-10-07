"""Tests for WG5-series thermostats (UWG5)."""

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.climate import (
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


@pytest.fixture(name="climate_entity_id")
async def climate_entity_id_fixture(
    hass: HomeAssistant,
    mock_wg5_config_entry: MockConfigEntry,
    mock_wg5_api: AiohttpClientMocker,
) -> str:
    """Set up a WG5-series entry and return its climate entity."""
    assert mock_wg5_api
    mock_wg5_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_wg5_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_wg5_config_entry.state is ConfigEntryState.LOADED
    return "climate.bathroom"


@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        ("climate.bathroom", "heat"),
        ("binary_sensor.bathroom_heating", "on"),
        ("binary_sensor.bathroom_online", "on"),
        ("sensor.bathroom_temperature_room", "21.0"),
        ("sensor.bathroom_temperature_floor", "19.0"),
        ("sensor.bathroom_sensor_mode", "Floor"),
    ],
)
async def test_entities(
    hass: HomeAssistant, climate_entity_id: str, entity_id: str, state: str
) -> None:
    """Test a WG5-series thermostat creates its entities, without errors."""
    assert climate_entity_id
    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    assert entity_state.state == state


async def test_presets(hass: HomeAssistant, climate_entity_id: str) -> None:
    """Test the presets offered for a WG5-series thermostat."""
    state = hass.states.get(climate_entity_id)
    assert state is not None
    assert state.attributes["preset_modes"] == [
        "schedule",
        "manual",
        "comfort",
        "vacation",
        "frost_protection",
    ]


async def test_set_temperature(
    hass: HomeAssistant, climate_entity_id: str, mock_wg5_api: AiohttpClientMocker
) -> None:
    """Test setting the temperature puts the thermostat in manual mode."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_TEMPERATURE: 21.5},
        blocking=True,
    )

    requests = [
        call
        for call in mock_wg5_api.mock_calls
        if call[0] == "PUT" and call[1].path.endswith("/mode")
    ]
    assert len(requests) == 1
    assert requests[0][2]["Setpoint"] == 21.5
