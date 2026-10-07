"""Tests for the OJ Microline Thermostat climate entities."""

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE

from .conftest import WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


@pytest.fixture(name="setup_integration")
async def setup_integration_fixture(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> AiohttpClientMocker:
    """Set up the integration and accept thermostat updates."""
    mock_wg4_api.post(
        f"{WG4_HOST}/api/thermostat",
        json={"Success": True},
        headers={"Content-Type": "application/json"},
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_wg4_api


def _update_requests(aioclient_mock: AiohttpClientMocker) -> list[object]:
    return [
        call
        for call in aioclient_mock.mock_calls
        if call[0] == "POST" and call[1].path == "/api/thermostat"
    ]


async def test_state(hass: HomeAssistant, setup_integration: object) -> None:
    """Test the state and attributes of a thermostat."""
    assert setup_integration
    state = hass.states.get("climate.roomname")
    assert state is not None
    assert state.state == "heat"
    assert state.attributes[ATTR_TEMPERATURE] == 26.0


async def test_set_temperature(
    hass: HomeAssistant, setup_integration: AiohttpClientMocker
) -> None:
    """Test setting the temperature updates the thermostat."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.roomname", ATTR_TEMPERATURE: 21.5},
        blocking=True,
    )

    requests = _update_requests(setup_integration)
    assert len(requests) == 1


async def test_set_preset_mode(
    hass: HomeAssistant, setup_integration: AiohttpClientMocker
) -> None:
    """Test setting a preset updates the thermostat."""
    state = hass.states.get("climate.roomname")
    assert state is not None
    preset = state.attributes["preset_modes"][0]

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: "climate.roomname", ATTR_PRESET_MODE: preset},
        blocking=True,
    )

    assert len(_update_requests(setup_integration)) == 1
