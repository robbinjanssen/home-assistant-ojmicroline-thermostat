"""Tests for WD5-series thermostats."""

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
    mock_wd5_config_entry: MockConfigEntry,
    mock_wd5_api: AiohttpClientMocker,
) -> str:
    """Set up a WD5-series entry and return its first climate entity."""
    assert mock_wd5_api
    mock_wd5_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_wd5_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_wd5_config_entry.state is ConfigEntryState.LOADED
    return min(hass.states.async_entity_ids(CLIMATE_DOMAIN))


def _group_updates(aioclient_mock: AiohttpClientMocker) -> int:
    return sum(
        1
        for call in aioclient_mock.mock_calls
        if call[1].path == "/api/Group/UpdateGroup"
    )


async def test_setup(hass: HomeAssistant, climate_entity_id: str) -> None:
    """Test a WD5-series thermostat creates its entities."""
    assert hass.states.get(climate_entity_id) is not None
    assert len(hass.states.async_all()) > 5


async def test_set_temperature(
    hass: HomeAssistant, climate_entity_id: str, mock_wd5_api: AiohttpClientMocker
) -> None:
    """Test setting the temperature updates the thermostat group."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_TEMPERATURE: 21.5},
        blocking=True,
    )

    assert _group_updates(mock_wd5_api) == 1


async def test_set_presets(
    hass: HomeAssistant, climate_entity_id: str, mock_wd5_api: AiohttpClientMocker
) -> None:
    """Test every preset updates the thermostat group."""
    state = hass.states.get(climate_entity_id)
    assert state is not None
    presets = state.attributes["preset_modes"]

    for preset in presets:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: preset},
            blocking=True,
        )

    assert _group_updates(mock_wd5_api) == len(presets)
