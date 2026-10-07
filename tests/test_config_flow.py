"""Tests for the OJ Microline Thermostat config and options flow."""

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from .conftest import DOMAIN, WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

WG4_INPUT = {"username": "user@example.com", "password": "pw"}


async def _start_wg4_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model": "WG4 series"}
    )
    assert result["step_id"] == "wg4"
    return result["flow_id"]


@pytest.mark.usefixtures("mock_wg4_api")
async def test_create_wg4_entry(hass: HomeAssistant) -> None:
    """Test creating an entry for a WG4-series account."""
    flow_id = await _start_wg4_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, WG4_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "OJ Microline Thermostat (user@example.com)"
    assert result["data"]["model"] == "WG4 series"
    assert result["data"]["username"] == "user@example.com"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"json": {"ErrorCode": 1}}, "invalid_auth"),
        ({"status": 500}, "connection_failed"),
    ],
)
async def test_wg4_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, object],
    error: str,
) -> None:
    """Test login errors are shown in the form."""
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        headers={"Content-Type": "application/json"},
        **response,
    )
    flow_id = await _start_wg4_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, WG4_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test changing the comfort mode options."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"use_comfort_mode": True, "comfort_mode_duration": 60},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        "use_comfort_mode": True,
        "comfort_mode_duration": 60,
    }
