"""Tests for the OJ Microline Thermostat config and options flow."""

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import DOMAIN, WG4_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
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


async def test_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test entering a new password updates and reloads the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    coordinator = mock_config_entry.runtime_data

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["username"] == "user@example.com"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "new-password"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "new-password"
    assert mock_config_entry.runtime_data is not coordinator
    assert mock_wg4_api.call_count > 0


async def test_reauth_wrong_password(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a rejected password keeps the form open."""
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"ErrorCode": 1},
        headers={"Content-Type": "application/json"},
    )
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data["password"] == "pw"


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_reload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test changing the options reloads the entry so they apply right away."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    coordinator = mock_config_entry.runtime_data

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_comfort_mode": True, "comfort_mode_duration": 60}
    )
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data is not coordinator


@pytest.mark.usefixtures("mock_wg5_api")
async def test_create_wg5_entry(hass: HomeAssistant) -> None:
    """Test creating an entry for a WG5-series (UWG5) account."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model": "WG5 series"}
    )
    assert result["step_id"] == "wg5"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "user@example.com", "password": "pw"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "model": "WG5 series",
        "username": "user@example.com",
        "password": "pw",
    }


async def test_reconfigure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test changing the account settings updates and reloads the entry."""
    assert mock_wg4_api
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    coordinator = mock_config_entry.runtime_data

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"username": "user@example.com", "password": "new-pw", "application": 4},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        "model": "WG4 series",
        "username": "user@example.com",
        "password": "new-pw",
        "application": 4,
    }
    assert mock_config_entry.runtime_data is not coordinator


async def test_reconfigure_wrong_password(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a rejected login keeps the form open and the entry unchanged."""
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user",
        json={"ErrorCode": 1},
        headers={"Content-Type": "application/json"},
    )
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "user@example.com", "password": "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data["password"] == "pw"


async def test_reconfigure_to_existing_account(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test an entry cannot be changed into another configured account."""
    mock_config_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"model": "WG4 series", "username": "other@example.com", "password": "x"},
    ).add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "other@example.com", "password": "pw"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data["username"] == "user@example.com"


async def test_reconfigure_form_per_model(
    hass: HomeAssistant, mock_wg5_config_entry: MockConfigEntry
) -> None:
    """Test the form asks for the fields of the entry's thermostat series."""
    mock_wg5_config_entry.add_to_hass(hass)

    result = await mock_wg5_config_entry.start_reconfigure_flow(hass)

    data_schema = result["data_schema"]
    assert data_schema is not None
    assert [str(key) for key in data_schema.schema] == ["username", "password"]
