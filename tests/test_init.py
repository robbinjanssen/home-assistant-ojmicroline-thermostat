"""Tests for setting up the OJ Microline Thermostat integration."""

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from ojmicroline_thermostat import OJMicrolineError, Thermostat
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.ojmicroline_thermostat import (
    async_migrate_entry,
    async_remove_config_entry_device,
)

from . import load_fixture
from .conftest import DOMAIN, WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr
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


@pytest.mark.usefixtures("mock_wg4_api")
async def test_setup_when_energy_usage_fails(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the thermostats are set up even if the energy usage fails."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ojmicroline_thermostat.energy.EnergyStatistics.async_today",
        side_effect=OJMicrolineError("Unable to get energy usage via API."),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get("climate.roomname")
    assert state is not None
    assert state.state == "heat"


@pytest.mark.usefixtures("mock_wg4_api")
async def test_failed_energy_request_does_not_refetch_others(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test one failing energy request does not fetch every thermostat again."""
    requested: list[str] = []

    async def today(thermostat: Thermostat) -> list[float]:
        requested.append(thermostat.serial_number)
        if thermostat.serial_number == "42424243":
            msg = "Unable to get energy usage via API."
            raise OJMicrolineError(msg)
        return [1.0]

    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.ojmicroline_thermostat.energy.EnergyStatistics.async_today",
        side_effect=today,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert sorted(requested) == ["42424242", "42424243"]

        requested.clear()
        await mock_config_entry.runtime_data.async_refresh()

    # The successful one waits for the update interval, the failed one for
    # the retry interval.
    assert not requested


@pytest.mark.usefixtures("mock_wg4_api")
async def test_hanging_energy_request(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a hanging energy request does not fail the whole update."""

    async def hang(_thermostat: Thermostat) -> list[float]:
        await asyncio.Event().wait()
        return []

    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.ojmicroline_thermostat.coordinator.API_TIMEOUT", 0.05),
        patch(
            "custom_components.ojmicroline_thermostat.energy.EnergyStatistics.async_today",
            side_effect=hang,
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get("climate.roomname")
    assert state is not None
    assert state.state == "heat"


def _mock_wg4_thermostats(
    aioclient_mock: AiohttpClientMocker, serial_numbers: set[str]
) -> None:
    """Let the WG4 API return only the thermostats with these serial numbers."""
    groups = json.loads(load_fixture("wg4_group.json"))
    for group in groups["Groups"]:
        group["Thermostats"] = [
            thermostat
            for thermostat in group["Thermostats"]
            if thermostat.get("SerialNumber") in serial_numbers
        ]
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"SessionId": "f00b4r", "ErrorCode": 0},
        headers={"Content-Type": "application/json"},
    )
    aioclient_mock.get(
        f"{WG4_HOST}/api/thermostats",
        json=groups,
        headers={"Content-Type": "application/json"},
    )
    aioclient_mock.get(
        f"{WG4_HOST}/api/energyusage",
        text=load_fixture("wg4_energy.json"),
        headers={"Content-Type": "application/json"},
    )


async def test_removed_thermostat_device_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the device of a thermostat removed from the account is removed."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, "42424243"), mock_config_entry.entry_id
        )
        is not None
    )

    _mock_wg4_thermostats(mock_wg4_api, {"42424242"})
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, "42424243"), mock_config_entry.entry_id
        )
        is None
    )
    assert hass.states.get("climate.secondroom") is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, "42424242"), mock_config_entry.entry_id
        )
        is not None
    )
    assert hass.states.get("climate.roomname") is not None
    # No deprecated device registry calls.
    assert "Detected that custom integration" not in caplog.text


async def test_empty_account_keeps_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test an account without thermostats does not remove every device."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

    _mock_wg4_thermostats(mock_wg4_api, set())
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, "42424242"), mock_config_entry.entry_id
        )
        is not None
    )
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, "42424243"), mock_config_entry.entry_id
        )
        is not None
    )


@pytest.mark.usefixtures("mock_wg4_api")
async def test_remove_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test only devices of thermostats no longer in the account can be deleted."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    current = device_registry.async_get_device_by_identifier(
        (DOMAIN, "42424242"), mock_config_entry.entry_id
    )
    assert current is not None
    removed = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, "99999999")},
    )

    assert not await async_remove_config_entry_device(hass, mock_config_entry, current)
    assert await async_remove_config_entry_device(hass, mock_config_entry, removed)


async def test_remove_device_not_loaded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test a device cannot be deleted while the account data is unknown."""
    mock_config_entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, "42424242")},
    )

    assert not await async_remove_config_entry_device(hass, mock_config_entry, device)
