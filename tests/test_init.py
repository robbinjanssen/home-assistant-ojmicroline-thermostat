"""Tests for setting up the OJ Microline Thermostat integration."""

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ojmicroline_thermostat import async_migrate_entry

from .conftest import DOMAIN, WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


@pytest.mark.usefixtures("mock_wg4_api")
async def test_setup_and_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test setting up and unloading a WG4-series entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.roomname") is not None
    assert hass.states.get("climate.secondroom") is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test wrong credentials stop the setup and start reauthentication."""
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"ErrorCode": 1},
        headers={"Content-Type": "application/json"},
    )
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a connection error retries the setup later."""
    aioclient_mock.post(f"{WG4_HOST}/api/authenticate/user", status=500)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_migrate_version_1(hass: HomeAssistant) -> None:
    """Test version 1 entries, which only supported WD5, get the model."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={"username": "user", "password": "pw", "api_key": "key"},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 2
    assert entry.data["model"] == "WD5 series"
