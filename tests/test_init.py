"""Tests for setting up the OJ Microline Thermostat integration."""

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.ojmicroline_thermostat import async_migrate_entry

from . import load_fixture
from .conftest import DOMAIN, WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )
    from yarl import URL


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


async def test_expired_session_logs_in_again(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test a rejected session is replaced instead of failing for hours (#140)."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    coordinator = mock_config_entry.runtime_data
    logins = _count(mock_wg4_api, "/api/authenticate/user")

    rejected = False

    async def reject_once(
        method: str, url: URL, _data: object
    ) -> AiohttpClientMockResponse:
        nonlocal rejected
        if not rejected:
            rejected = True
            return AiohttpClientMockResponse(method, url, status=401)
        return AiohttpClientMockResponse(
            method,
            url,
            text=load_fixture("wg4_group.json"),
            headers={"Content-Type": "application/json"},
        )

    mock_wg4_api.clear_requests()
    mock_wg4_api.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"SessionId": "n3ws3ss10n", "ErrorCode": 0},
        headers={"Content-Type": "application/json"},
    )
    mock_wg4_api.get(f"{WG4_HOST}/api/thermostats", side_effect=reject_once)
    mock_wg4_api.get(
        f"{WG4_HOST}/api/energyusage",
        text=load_fixture("wg4_energy.json"),
        headers={"Content-Type": "application/json"},
    )

    await coordinator.async_refresh()

    assert rejected
    assert coordinator.last_update_success
    assert _count(mock_wg4_api, "/api/authenticate/user") == 1
    assert logins >= 1


def _count(aioclient_mock: AiohttpClientMocker, path: str) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if call[1].path == path)


async def test_setup_auth_failed_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a rejected password asks the user for the new one."""
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"ErrorCode": 1},
        headers={"Content-Type": "application/json"},
    )
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
