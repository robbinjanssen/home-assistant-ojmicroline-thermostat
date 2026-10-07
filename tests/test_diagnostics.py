"""Tests for the OJ Microline Thermostat diagnostics."""

from typing import TYPE_CHECKING

import pytest

from custom_components.ojmicroline_thermostat.diagnostics import (
    async_get_config_entry_diagnostics,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.mark.usefixtures("mock_wg4_api")
async def test_diagnostics_redacted(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test credentials are redacted from the diagnostics."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert "user@example.com" not in str(diagnostics)
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
