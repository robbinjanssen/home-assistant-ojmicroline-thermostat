"""Fixtures for the OJ Microline Thermostat integration tests."""

import importlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import load_fixture

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

# Import the integration before pytest-homeassistant-custom-component imports
# its own custom_components package, so Home Assistant can find it.
importlib.import_module("custom_components.ojmicroline_thermostat")

DOMAIN = "ojmicroline_thermostat"
WG4_HOST = "https://mythermostat.info"
WG4_DATA = {"model": "WG4 series", "username": "user@example.com", "password": "pw"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: None,  # pylint: disable=unused-argument
    enable_custom_integrations: None,  # pylint: disable=unused-argument
) -> None:
    """Enable custom integrations and the recorder the integration depends on."""


@pytest.fixture(autouse=True)
def mock_frontend(hass: HomeAssistant) -> Generator[MagicMock]:
    """Skip the frontend and http dependencies, which serve the schedule card."""
    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch(
        "custom_components.ojmicroline_thermostat.add_extra_js_url"
    ) as add_extra_js_url:
        yield add_extra_js_url


@pytest.fixture(autouse=True)
def mock_delayed_refresh() -> Generator[None]:
    """Refresh right away instead of waiting for the API to catch up."""
    with (
        patch(
            "custom_components.ojmicroline_thermostat.climate."
            "OJMicrolineThermostat._async_delayed_request_refresh",
        ),
        patch(
            "custom_components.ojmicroline_thermostat.coordinator."
            "OJMicrolineDataUpdateCoordinator.async_request_delayed_refresh",
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_subscribe() -> Generator[None]:
    """Do not start waiting for push notifications in the background."""
    with patch(
        "ojmicroline_thermostat.OJMicroline.subscribe", return_value=lambda: None
    ):
        yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for a WG4-series account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="OJ Microline Thermostat (user@example.com)",
        version=2,
        data=WG4_DATA,
        entry_id="01JOJMICROLINE",
    )


@pytest.fixture
def mock_wg4_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Respond to the requests of a WG4-series account."""
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"SessionId": "f00b4r", "ErrorCode": 0},
        headers={"Content-Type": "application/json"},
    )
    aioclient_mock.get(
        f"{WG4_HOST}/api/thermostats",
        text=load_fixture("wg4_group.json"),
        headers={"Content-Type": "application/json"},
    )
    aioclient_mock.get(
        f"{WG4_HOST}/api/energyusage",
        text=load_fixture("wg4_energy.json"),
        headers={"Content-Type": "application/json"},
    )
    return aioclient_mock


WD5_HOST = "https://ocd5.azurewebsites.net"
WD5_DATA = {
    "model": "WD5 series",
    "username": "user@example.com",
    "password": "pw",
    "api_key": "api-key",
}


@pytest.fixture
def mock_wd5_config_entry() -> MockConfigEntry:
    """Return a config entry for a WD5-series account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="OJ Microline Thermostat (user@example.com)",
        version=2,
        data=WD5_DATA,
        entry_id="01JOJMICROLINEWD5",
    )


@pytest.fixture
def mock_wd5_api(aioclient_mock: AiohttpClientMocker) -> Generator[AiohttpClientMocker]:
    """Respond to the requests of a WD5-series account, without push updates."""
    json_headers = {"Content-Type": "application/json"}
    aioclient_mock.post(
        f"{WD5_HOST}/api/UserProfile/SignIn",
        json={"SessionId": "f00b4r", "UserName": "user", "ErrorCode": 0},
        headers=json_headers,
    )
    aioclient_mock.get(
        f"{WD5_HOST}/api/Group/GroupContents",
        text=load_fixture("wd5_group.json"),
        headers=json_headers,
    )
    aioclient_mock.post(
        f"{WD5_HOST}/api/EnergyUsage/GetEnergyUsage",
        text=load_fixture("energy.json"),
        headers=json_headers,
    )
    aioclient_mock.post(
        f"{WD5_HOST}/api/Group/UpdateGroup",
        json={"ErrorCode": 0},
        headers=json_headers,
    )
    with patch("custom_components.ojmicroline_thermostat.push.WD5PushClient.start"):
        yield aioclient_mock


WG5_IDENTITY = "https://identity.ojmicroline.com"
WG5_HOST = "https://user-api.ojmicroline.com"
WG5_BUILDING = "57dc7778-4ed3-4382-9e89-5cf2e0bc0f8a"
WG5_THERMOSTAT = "2cb3e6c5-8cf8-4e7e-943a-42618c34a506"
WG5_SCHEDULE = "f9aac20b-4e45-415b-9f56-e53014ee8639"
WG5_DATA = {"model": "WG5 series", "username": "user@example.com", "password": "pw"}


@pytest.fixture
def mock_wg5_config_entry() -> MockConfigEntry:
    """Return a config entry for a WG5-series account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="OJ Microline Thermostat (user@example.com)",
        version=2,
        data=WG5_DATA,
        entry_id="01JOJMICROLINEWG5",
    )


@pytest.fixture
def mock_wg5_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Respond to the requests of a WG5-series account."""
    json_headers = {"Content-Type": "application/json"}
    aioclient_mock.post(
        f"{WG5_IDENTITY}/connect/token",
        text=load_fixture("wg5_token.json"),
        headers=json_headers,
    )
    for path, fixture in (
        ("buildings", "wg5_buildings.json"),
        (f"buildings/{WG5_BUILDING}/tree", "wg5_building_tree.json"),
        (f"thermostats/{WG5_THERMOSTAT}/control", "wg5_thermostat_control.json"),
        (f"thermostats/{WG5_THERMOSTAT}", "wg5_thermostat_detail.json"),
        (f"schedules/{WG5_SCHEDULE}", "wg5_schedule.json"),
    ):
        aioclient_mock.get(
            f"{WG5_HOST}/{path}", text=load_fixture(fixture), headers=json_headers
        )
    aioclient_mock.get(
        f"{WG5_HOST}/awaymode/{WG5_BUILDING}",
        json={"status": {"code": "OK"}},
        headers=json_headers,
    )
    aioclient_mock.post(
        f"{WG5_HOST}/energy/usage/building/{WG5_BUILDING}",
        text=load_fixture("wg5_energy.json"),
        headers=json_headers,
    )
    aioclient_mock.put(
        f"{WG5_HOST}/thermostats/{WG5_THERMOSTAT}/mode",
        json={"status": {"code": "OK"}},
        headers=json_headers,
    )
    return aioclient_mock
