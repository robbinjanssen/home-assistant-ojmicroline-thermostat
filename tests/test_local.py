"""Exercise local startup, private profile migration, and HA entity control."""

import hashlib
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.storage import Store
from ojmicroline_thermostat import OJMicrolineError

from custom_components.ojmicroline_thermostat.local import WG4LocalTransport
from custom_components.ojmicroline_thermostat.local_profile import (
    async_load_profile,
    profile_store,
    validate_profile,
)

from . import load_fixture
from .conftest import DOMAIN
from .test_local_gateway import CONFIG, SUPPORT

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

# These tests exercise the adapter's resource conversion and gateway callback.
# pylint: disable=protected-access,redefined-outer-name


@pytest.fixture
def local_seed() -> dict[str, dict[str, Any]]:
    """Use upstream's synthetic WG4 fixture with one thermostat."""
    raw = json.loads(load_fixture("wg4_group.json"))
    device = next(t for t in raw["Groups"][0]["Thermostats"] if t)
    return {str(device["SerialNumber"]): device}


@pytest.fixture
def local_profile(local_seed: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Build a synthetic profile, without captured personal configuration."""
    serial, device = next(iter(local_seed.items()))
    return {
        "serial_sha256": hashlib.sha256(serial.encode()).hexdigest(),
        "firmware": device["SWVersion"],
        "configuration": CONFIG.hex(),
        "support": SUPPORT.hex(),
    }


@pytest.fixture
def local_gateway() -> Generator[MagicMock]:
    """Replace network I/O while retaining the real transport and HA lifecycle."""
    gateway = MagicMock(start=AsyncMock(), stop=AsyncMock(), queue_set=AsyncMock())
    gateway.cancel_pending.return_value = False
    gateway.is_waiting_for_ack.return_value = False
    with (
        patch(
            "custom_components.ojmicroline_thermostat.local.LocalGateway",
            return_value=gateway,
        ),
        patch(
            "custom_components.ojmicroline_thermostat.local.async_ensure_cert",
            AsyncMock(return_value=("cert", "key")),
        ),
    ):
        yield gateway


async def _seed_storage(
    hass: HomeAssistant,
    entry_id: str,
    seed: dict[str, dict[str, Any]],
    profile: dict[str, str],
) -> None:
    """Save a validated profile and metadata as a prior setup would."""
    await profile_store(hass, entry_id).async_save(validate_profile(profile))
    store: Store[dict[str, dict[str, Any]]] = Store(
        hass, 1, f"{DOMAIN}.{entry_id}.local_seed"
    )
    await store.async_save(seed)


async def test_local_ha_setup_control_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    local_seed: dict[str, dict[str, Any]],
    local_profile: dict[str, str],
    local_gateway: MagicMock,
) -> None:
    """Keep the cloud entity identity and serve controls/reloads without HTTP."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"local_control": True}
    )
    await _seed_storage(hass, mock_config_entry.entry_id, local_seed, local_profile)
    serial = next(iter(local_seed))
    local_gateway.connected_serials = {serial}
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    transport = mock_config_entry.runtime_data.local
    assert isinstance(transport, WG4LocalTransport)
    transport._on_state(
        serial,
        {"Online": True, "Temperature": 2100, "Heating": False},
    )
    await hass.async_block_till_done()
    state = hass.states.get("climate.roomname")
    assert state is not None
    assert state.state != "unavailable"
    assert state.attributes["current_temperature"] == 21
    assert state.attributes["preset_modes"] == ["schedule", "manual"]
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.roomname", "temperature": 22},
        blocking=True,
    )
    local_gateway.queue_set.assert_awaited_with(serial, 3, 4400)
    device = (await transport.async_get_thermostats())[0]
    assert device.energy is None
    assert device.supported_regulation_modes == [1, 3]
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    local_gateway.stop.assert_awaited_once()
    assert local_gateway.start.await_count == 2
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("change", ["firmware", "serial_sha256"])
async def test_mismatched_profile_refuses_listener(  # noqa: PLR0913, PLR0917
    # pylint: disable=too-many-arguments
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    local_seed: dict[str, dict[str, Any]],
    local_profile: dict[str, str],
    local_gateway: MagicMock,
    change: str,
) -> None:
    """Avoid serving another thermostat's configuration."""
    local_profile[change] = "0" * 64
    await _seed_storage(hass, mock_config_entry.entry_id, local_seed, local_profile)
    transport = WG4LocalTransport(
        hass, mock_config_entry, MagicMock(), MagicMock(), MagicMock()
    )
    with pytest.raises(OJMicrolineError, match="does not match"):
        await transport.async_get_thermostats()
    local_gateway.start.assert_not_awaited()


@pytest.mark.parametrize(
    ("mode", "temperature", "connected", "pending", "template", "message"),
    [
        (2, 2000, True, False, True, "supports schedule"),
        (3, 99999, True, False, True, "outside"),
        (3, 2000, False, False, True, "not connected"),
        (3, 2000, True, True, True, "could not be sent"),
        (3, 2000, True, False, False, "state and schedule"),
    ],
)
async def test_rejected_local_commands(  # noqa: PLR0913, PLR0917
    # pylint: disable=too-many-arguments
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    local_seed: dict[str, dict[str, Any]],
    local_profile: dict[str, str],
    local_gateway: MagicMock,
    mode: int,
    temperature: int,
    *,
    connected: bool,
    pending: bool,
    template: bool,
    message: str,
) -> None:
    """Reject unsupported or undeliverable commands instead of applying later."""
    await _seed_storage(hass, mock_config_entry.entry_id, local_seed, local_profile)
    transport = WG4LocalTransport(
        hass, mock_config_entry, MagicMock(), MagicMock(), MagicMock()
    )
    device = (await transport.async_get_thermostats())[0]
    local_gateway.connected_serials = {device.serial_number} if connected else set()
    local_gateway.cancel_pending.return_value = pending
    local_gateway.has_command_template.return_value = template
    with pytest.raises(OJMicrolineError, match=message):
        await transport.async_set_mode(device, mode, temperature)
    await transport.async_stop()


async def test_profile_import_is_saved_privately(
    hass: HomeAssistant, tmp_path: Path, local_profile: dict[str, str]
) -> None:
    """Import once and continue loading after the source file is removed."""
    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / DOMAIN
    folder.mkdir()
    path = folder / "local_profile.json"
    path.write_text(json.dumps(local_profile))
    assert await async_load_profile(hass, "test") == local_profile
    path.unlink()
    assert await async_load_profile(hass, "test") == local_profile


async def test_missing_profile_is_actionable(hass: HomeAssistant) -> None:
    """Reject enabling local control until a private profile exists."""
    with pytest.raises(ValueError, match="Import a captured local profile"):
        await async_load_profile(hass, "absent")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("firmware", ""),
        ("serial_sha256", "bad"),
        ("configuration", "08"),
        ("support", "not hex"),
        ("configuration", "08024a00"),  # state command, not configuration
    ],
)
def test_invalid_profile_rejected(
    local_profile: dict[str, str], key: str, value: str
) -> None:
    """Refuse missing identity and malformed or command-bearing frames."""
    local_profile[key] = value
    with pytest.raises(ValueError, match=r"[Pp]rofile"):
        validate_profile(local_profile)


async def test_first_setup_seeds_cloud_metadata_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    local_seed: dict[str, dict[str, Any]],
    local_profile: dict[str, str],
    local_gateway: MagicMock,
) -> None:
    """Fetch metadata only when the private startup cache is absent."""
    await profile_store(hass, mock_config_entry.entry_id).async_save(
        validate_profile(local_profile)
    )
    model = MagicMock(
        request=AsyncMock(
            return_value={"Groups": [{"Thermostats": list(local_seed.values())}]}
        )
    )
    cloud = MagicMock(login=AsyncMock())
    transport = WG4LocalTransport(hass, mock_config_entry, model, cloud, MagicMock())
    await transport.async_get_thermostats()
    await transport.async_get_thermostats()
    cloud.login.assert_awaited_once()
    model.request.assert_awaited_once()
    local_gateway.start.assert_awaited_once()
    await transport.async_stop()


async def test_port_conflict_cleans_up(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    local_seed: dict[str, dict[str, Any]],
    local_profile: dict[str, str],
    local_gateway: MagicMock,
) -> None:
    """Release failed startup resources and report the fixed device port."""
    await _seed_storage(hass, mock_config_entry.entry_id, local_seed, local_profile)
    local_gateway.start.side_effect = OSError("port in use")
    transport = WG4LocalTransport(
        hass, mock_config_entry, MagicMock(), MagicMock(), MagicMock()
    )
    with pytest.raises(OJMicrolineError, match="port 9533"):
        await transport.async_get_thermostats()
    local_gateway.stop.assert_awaited_once()
