"""Tests for the OJ Microline Thermostat energy price."""

from typing import TYPE_CHECKING, Any
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.components.number import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import WG4_HOST

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

ENTITY_ID = "number.roomname_energy_price"


@pytest.fixture(name="entity_registry_enabled_by_default")
def entity_registry_enabled_by_default_fixture() -> Generator[None]:
    """Enable entities that are disabled by default, like Home Assistant core."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


async def _setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
) -> None:
    aioclient_mock.post(
        f"{WG4_HOST}/api/thermostat",
        headers={"Content-Type": "application/json"},
        **response,
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("mock_wg4_api")
async def test_disabled_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the energy price is disabled by default, as it reprices old usage."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entry = entity_registry.async_get(ENTITY_ID)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_set_energy_price(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test setting the energy price sends it and shows it right away."""
    await _setup(hass, mock_config_entry, mock_wg4_api, {"json": {"Success": True}})
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "0.25"
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "EUR/kWh"

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: 0.0894},
        blocking=True,
    )

    updates = [
        data
        for method, url, data, _ in mock_wg4_api.mock_calls
        if method == "POST" and url.path == "/api/thermostat"
    ]
    assert updates == [{"KwhCharge": "0.0894"}]
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "0.0894"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_set_energy_price_refused(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test a refused energy price is reported and not shown."""
    await _setup(hass, mock_config_entry, mock_wg4_api, {"json": {"Success": False}})

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: 0.5},
            blocking=True,
        )

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "0.25"


@pytest.mark.usefixtures("mock_wd5_api", "entity_registry_enabled_by_default")
async def test_not_created_for_wd5(
    hass: HomeAssistant,
    mock_wd5_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test WD5-series thermostats, which have no energy price, get no entity."""
    mock_wd5_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_wd5_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not [
        entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, mock_wd5_config_entry.entry_id
        )
        if entry.domain == NUMBER_DOMAIN
    ]
