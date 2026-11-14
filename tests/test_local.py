"""Tests for the local gateway of WG4-series and WD5-series accounts.

The gateway itself is tested in the library. Here it does not listen on a
port: the tests let it report as if a thermostat were connected.
"""

import json
import ssl
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.climate import (
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from ojmicroline_thermostat import (
    WD5_R1099,
    WG4_NORTH_AMERICA,
    DeviceProfile,
    GatewayMode,
    OJMicrolineConnectionError,
    OJMicrolineError,
    UpstreamStatus,
    WD5Gateway,
    WG4Gateway,
)
from ojmicroline_thermostat.const import (
    REGULATION_COMFORT,
    REGULATION_FROST_PROTECTION,
    REGULATION_MANUAL,
    REGULATION_SCHEDULE,
)
from ojmicroline_thermostat.gateway.protobuf import encode_field, encode_frame
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ojmicroline_thermostat import local
from custom_components.ojmicroline_thermostat.diagnostics import (
    async_get_config_entry_diagnostics,
)

from . import load_fixture
from .conftest import DOMAIN, WD5_DATA, WG4_DATA, WG4_HOST

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from homeassistant.core import HomeAssistant, State
    from homeassistant.helpers import issue_registry as ir
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

ENTRY_ID = "01JOJMICROLINE"
STORE_KEY = f"{DOMAIN}.{ENTRY_ID}.gateway"
# The thermostats in the fixture of the cloud API.
SERIAL = "42424242"
OTHER = "42424243"
# Those of the WD5-series account, which is of the SWATT app.
WD5_SERIAL = "800747"
WD5_OTHER = "800857"

MODULE = "custom_components.ojmicroline_thermostat"
JSON = {"Content-Type": "application/json"}

# The function that creates the certificate; the tests replace it in the
# module, so it is kept here for the test of the function itself.
load_ssl_context = local._load_ssl_context  # pylint: disable=protected-access

# The two answers of OJ's gateway, with made-up content.
PROFILE = DeviceProfile(
    configuration=encode_frame(encode_field(10, b"configuration")),
    support=encode_frame(encode_field(18, b"support")),
)


def _snapshot() -> dict[str, Any]:
    """Return the thermostats of the cloud fixture as a stored snapshot."""
    groups = json.loads(load_fixture("wg4_group.json"))["Groups"]
    return {
        item["SerialNumber"]: item
        for group in groups
        for item in group["Thermostats"]
        if item
    }


def _stored(*, profile: bool = True) -> dict[str, Any]:
    """Return what the gateway stored after a thermostat was relayed."""
    return {
        "version": 1,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {
            "snapshot": _snapshot(),
            "profiles": {SERIAL: PROFILE.to_dict()} if profile else {},
        },
    }


def _entry(mode: str, **options: Any) -> MockConfigEntry:
    """Return the config entry of a WG4-series account in a connection mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="OJ Microline Thermostat (user@example.com)",
        version=2,
        data=WG4_DATA,
        options={"connection_mode": mode, **options},
        entry_id=ENTRY_ID,
    )


def _wd5_entry(mode: str, **options: Any) -> MockConfigEntry:
    """Return the config entry of a WD5-series account in a connection mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="OJ Microline Thermostat (user@example.com)",
        version=2,
        data=WD5_DATA,
        options={"connection_mode": mode, **options},
        entry_id=ENTRY_ID,
    )


def _gateway(entry: MockConfigEntry) -> WG4Gateway:
    gateway: WG4Gateway = entry.runtime_data.local.gateway
    return gateway


def _report(entry: MockConfigEntry, serial: str, **fields: Any) -> None:
    """Let the gateway report something, as if a thermostat sent it.

    The thermostat counts as connected, answered locally, until it reports
    that it is offline.
    """
    gateway = _gateway(entry)
    links = gateway._links  # pylint: disable=protected-access
    if fields.get("Online") is False:
        links.pop(serial, None)
    else:
        links.setdefault(serial, Mock(upstream=None))
    report = gateway.on_state
    assert report is not None
    report(serial, fields)


async def _deliver(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Hand what the thermostats reported to Home Assistant.

    This is what the library's subscription does; the tests do not start one.
    """
    coordinator = entry.runtime_data
    for thermostat in await coordinator.local.api.get_notifications():
        coordinator._async_handle_push_thermostat(thermostat)  # pylint: disable=protected-access
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> State:
    """Return the state of an entity that has to exist."""
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _requests(aioclient_mock: AiohttpClientMocker, path: str) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if call[1].path == path)


@pytest.fixture(name="listener", autouse=True)
def listener_fixture() -> Generator[AsyncMock]:
    """Keep the gateway from listening on a port and from creating a certificate."""
    with (
        patch(
            f"{MODULE}.local._load_ssl_context",
            return_value=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER),
        ),
        patch(f"{MODULE}.local.WG4Gateway.start", new_callable=AsyncMock) as start,
        patch(f"{MODULE}.local.WG4Gateway.stop", new_callable=AsyncMock),
        patch(f"{MODULE}.local.WD5Gateway.start", start),
        patch(f"{MODULE}.local.WD5Gateway.stop", new_callable=AsyncMock),
    ):
        yield start


@pytest.mark.usefixtures("mock_wg4_api")
async def test_setup_and_unload(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    listener: AsyncMock,
) -> None:
    """Test the gateway runs with the entry, and stores the snapshot."""
    entry = _entry("relay")
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data
    assert coordinator.local.mode is GatewayMode.RELAY
    gateway = _gateway(entry)
    assert gateway.mode is GatewayMode.RELAY
    listener.assert_awaited_once()
    # Only the thermostats of the account may connect.
    assert gateway.allowed_serials == {SERIAL, OTHER}
    # No thermostat connected yet, so both are as the cloud describes them.
    assert _state(hass, "climate.roomname").state == "heat"
    assert _state(hass, "climate.secondroom").state == "heat"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    gateway.stop.assert_awaited_once()
    assert hass_storage[STORE_KEY]["data"]["snapshot"] == _snapshot()

    # Removing the entry forgets what was stored.
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert STORE_KEY not in hass_storage


@pytest.mark.usefixtures("mock_wg4_api")
async def test_cloud_mode_has_no_gateway(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, listener: AsyncMock
) -> None:
    """Test nothing listens unless a local connection mode is chosen."""
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.local is None
    listener.assert_not_awaited()
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["gateway"] is None


@pytest.mark.usefixtures("mock_wd5_api")
async def test_unknown_brand_has_no_gateway(
    hass: HomeAssistant, listener: AsyncMock
) -> None:
    """Test the connection mode means nothing without a known device gateway."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        # The OJ Microline app, whose device gateway is not known.
        data={**WD5_DATA, "customer_id": 1},
        options={"connection_mode": "relay"},
    )
    await _setup(hass, entry)

    assert entry.runtime_data.local is None
    listener.assert_not_awaited()


def test_endpoint_for() -> None:
    """Test which device gateway the thermostats of an account look for."""
    assert local.endpoint_for(WG4_DATA) is WG4_NORTH_AMERICA
    # Schlüter in North America, where schluter-local comes from.
    assert local.endpoint_for({**WG4_DATA, "application": 7}) is WG4_NORTH_AMERICA
    # Danfoss LX, whose thermostats may look elsewhere.
    assert local.endpoint_for({**WG4_DATA, "application": 4}) is None
    # Without a customer ID the account is of the SWATT app.
    assert local.endpoint_for(WD5_DATA) is WD5_R1099
    schluter = local.endpoint_for({**WD5_DATA, "customer_id": 3})
    assert schluter is not None
    assert schluter.host == "owd5-sl003-thermostat.ojelectronics.com"
    assert local.endpoint_for({**WD5_DATA, "customer_id": 1}) is None
    assert local.endpoint_for({"model": "WG5 series"}) is None


@pytest.mark.usefixtures("mock_wd5_api")
async def test_wd5_setup(hass: HomeAssistant, listener: AsyncMock) -> None:
    """Test a WD5-series account gets a gateway, and reports through it."""
    entry = _wd5_entry("local")
    with patch(f"{MODULE}.push.WD5PushClient.start") as hub:
        await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    listener.assert_awaited_once()
    # The thermostats report to the gateway, so the hub of the cloud is not used.
    hub.assert_not_called()
    gateway = entry.runtime_data.local.gateway
    assert isinstance(gateway, WD5Gateway)
    assert gateway.mode is GatewayMode.LOCAL
    assert gateway.endpoint is WD5_R1099
    assert gateway.allowed_serials == {WD5_SERIAL, WD5_OTHER}
    # A WD5 thermostat has no profile, and needs none to be answered.
    assert entry.runtime_data.local.profiles == {}
    assert await local.async_profiles(hass, entry) is None

    _report(entry, WD5_SERIAL, Online=True, RoomTemperature=2175, Heating=True)
    await _deliver(hass, entry)
    state = _state(hass, "climate.woonkamer")
    assert state.attributes["hvac_action"] == "heating"
    # The other thermostat never connected, and is still the cloud's.
    assert _state(hass, "climate.gang").attributes["hvac_action"] == "idle"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["gateway"]["mode"] == "local"
    assert diagnostics["gateway"]["profiles"] == 0


async def test_wd5_set_temperature_goes_to_the_gateway(
    hass: HomeAssistant, mock_wd5_api: AiohttpClientMocker
) -> None:
    """Test a thermostat on the gateway is set directly, another in the cloud."""
    entry = _wd5_entry("relay", use_comfort_mode=True, comfort_mode_duration=90)
    await _setup(hass, entry)
    send = AsyncMock()
    _gateway(entry).set_mode = send  # type: ignore[method-assign]
    _report(entry, WD5_SERIAL, Online=True)
    await _deliver(hass, entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.woonkamer", ATTR_TEMPERATURE: 21},
        blocking=True,
    )

    send.assert_awaited_once()
    arguments = send.await_args
    assert arguments is not None
    assert arguments.args == (WD5_SERIAL, REGULATION_COMFORT, 2100)
    # The comfort hold ends after the chosen duration, in thermostat time.
    assert arguments.kwargs["end"] is not None
    assert arguments.kwargs["known"]["SerialNumber"] == WD5_SERIAL
    assert _requests(mock_wd5_api, "/api/Group/UpdateGroup") == 0

    # A thermostat that never connected to the gateway is set in the cloud.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.gang", ATTR_TEMPERATURE: 20},
        blocking=True,
    )
    send.assert_awaited_once()
    assert _requests(mock_wd5_api, "/api/Group/UpdateGroup") == 1


@pytest.mark.usefixtures("mock_wd5_api")
async def test_wd5_options_flow(hass: HomeAssistant, listener: AsyncMock) -> None:
    """Test a WD5-series account can go local only without the relay first."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=WD5_DATA)
    await _setup(hass, entry)
    chosen = {
        "use_comfort_mode": False,
        "comfort_mode_duration": 240,
        "connection_mode": "local",
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], chosen
    )
    assert result["step_id"] == "gateway"
    assert result["description_placeholders"] == {
        "hostname": "owd5-r1099-thermostat.ojelectronics.com",
        "ip": "10.10.10.10",
        "port": "9513",
    }

    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    listener.assert_awaited_once()
    assert isinstance(entry.runtime_data.local.gateway, WD5Gateway)


@pytest.mark.usefixtures("mock_wg4_api")
async def test_port_in_use_retries_setup(
    hass: HomeAssistant, listener: AsyncMock
) -> None:
    """Test the setup is retried when the gateway cannot listen."""
    listener.side_effect = OJMicrolineConnectionError(
        "Unable to listen on port 9533: address already in use"
    )
    entry = _entry("relay")
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_wg4_api")
async def test_thermostat_reports_through_the_gateway(hass: HomeAssistant) -> None:
    """Test what a thermostat reports to the gateway reaches its entities."""
    entry = _entry("local")
    await _setup(hass, entry)

    _report(entry, SERIAL, Online=True)
    _report(entry, SERIAL, Temperature=1950, Heating=True)
    await _deliver(hass, entry)

    state = _state(hass, "climate.roomname")
    assert state.attributes["current_temperature"] == 19.5
    assert state.attributes["hvac_action"] == "heating"
    # The other thermostat never connected, and is still the cloud's.
    assert _state(hass, "climate.secondroom").attributes["hvac_action"] == "idle"

    # Once it disconnects, the thermostat is offline whatever the cloud says:
    # in local mode it does not reach the cloud.
    _report(entry, SERIAL, Online=False, Heating=False)
    await _deliver(hass, entry)
    assert _state(hass, "climate.roomname").attributes["hvac_action"] == "off"
    assert _state(hass, "binary_sensor.roomname_online").state == "off"


@pytest.mark.usefixtures("mock_wg4_api")
async def test_relayed_thermostat_that_left_is_the_clouds(
    hass: HomeAssistant,
) -> None:
    """Test a thermostat that left a relaying gateway is as the cloud says.

    It may connect to OJ's gateway directly then, which the cloud knows.
    """
    entry = _entry("relay")
    await _setup(hass, entry)
    _report(entry, SERIAL, Online=True)
    _report(entry, SERIAL, Online=False)
    await _deliver(hass, entry)
    assert _state(hass, "binary_sensor.roomname_online").state == "on"


async def test_set_temperature_goes_to_the_gateway(
    hass: HomeAssistant, mock_wg4_api: AiohttpClientMocker
) -> None:
    """Test a new temperature goes to the thermostat, not to the cloud."""
    entry = _entry("relay")
    await _setup(hass, entry)
    send = AsyncMock()
    _gateway(entry).set_mode = send  # type: ignore[method-assign]
    _report(entry, SERIAL, Online=True)
    await _deliver(hass, entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.roomname", ATTR_TEMPERATURE: 21},
        blocking=True,
    )

    send.assert_awaited_once_with(SERIAL, REGULATION_MANUAL, 2100)
    assert _requests(mock_wg4_api, "/api/thermostat") == 0
    assert _state(hass, "climate.roomname").attributes[ATTR_TEMPERATURE] == 21

    # An error of the gateway, such as a thermostat that went away, is shown.
    send.side_effect = OJMicrolineConnectionError("The thermostat is not connected")
    with pytest.raises(HomeAssistantError, match="not connected"):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: "climate.roomname", ATTR_TEMPERATURE: 22},
            blocking=True,
        )


async def test_local_only_without_the_cloud(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test local only works from what was stored, with the cloud unreachable."""
    hass_storage[STORE_KEY] = _stored()
    aioclient_mock.post(f"{WG4_HOST}/api/authenticate/user", status=500)
    entry = _entry("local", use_comfort_mode=True)
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    gateway = _gateway(entry)
    assert gateway.mode is GatewayMode.LOCAL
    assert gateway.profiles == {SERIAL: PROFILE}
    # A thermostat with a profile belongs on the gateway: until it connects
    # it is offline, whatever the stored snapshot says.
    assert _state(hass, "binary_sensor.roomname_online").state == "off"

    send = AsyncMock()
    gateway.set_mode = send  # type: ignore[method-assign]
    _report(entry, SERIAL, Online=True, RegulationMode=1)
    await _deliver(hass, entry)
    state = _state(hass, "climate.roomname")
    assert state.attributes["preset_modes"] == ["schedule", "manual"]
    assert state.attributes["preset_mode"] == "schedule"

    # The option asks for comfort mode, which needs the cloud; without it a
    # new temperature is a manual one.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.roomname", ATTR_TEMPERATURE: 21},
        blocking=True,
    )
    send.assert_awaited_once_with(SERIAL, REGULATION_MANUAL, 2100)
    # The energy usage is the cloud's, and the cloud is not asked.
    assert _requests(aioclient_mock, "/api/energyusage") == 0
    assert entry.runtime_data.data[SERIAL].energy is None


async def test_energy_usage_while_relayed(
    hass: HomeAssistant, mock_wg4_api: AiohttpClientMocker
) -> None:
    """Test a relayed thermostat still gets its energy usage from the cloud."""
    entry = _entry("relay")
    await _setup(hass, entry)

    assert _requests(mock_wg4_api, "/api/energyusage") > 0
    assert entry.runtime_data.data[SERIAL].energy is not None


async def test_rejected_password_keeps_thermostats_working(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a password the cloud refuses asks for a new one, and nothing more."""
    hass_storage[STORE_KEY] = _stored()
    aioclient_mock.post(
        f"{WG4_HOST}/api/authenticate/user", json={"ErrorCode": 1}, headers=JSON
    )
    entry = _entry("relay")
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.roomname") is not None
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert _requests(aioclient_mock, "/api/energyusage") == 0


@pytest.mark.usefixtures("mock_wg4_api")
async def test_profile_is_stored(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Test a profile the gateway records survives a restart."""
    entry = _entry("relay")
    await _setup(hass, entry)
    record = _gateway(entry).on_profile
    assert record is not None

    # The gateway keeps the profile itself, and tells its listener.
    _gateway(entry).profiles[SERIAL] = PROFILE
    record(SERIAL, PROFILE)
    known = await local.async_profiles(hass, entry)
    assert known is not None
    assert known[0] == {SERIAL}
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=local.PROFILE_SAVE_DELAY + 1)
    )
    await hass.async_block_till_done()

    assert hass_storage[STORE_KEY]["data"]["profiles"] == {SERIAL: PROFILE.to_dict()}


@pytest.mark.usefixtures("mock_wg4_api")
async def test_damaged_profile_is_ignored(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a stored profile that cannot be used is left out."""
    stored = _stored()
    stored["data"]["profiles"][SERIAL] = {"configuration": "00", "support": "00"}
    hass_storage[STORE_KEY] = stored
    entry = _entry("relay")
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert not _gateway(entry).profiles
    assert "Ignoring a stored profile that is damaged" in caplog.text


@pytest.mark.usefixtures("mock_wg4_api")
async def test_issue_when_no_thermostat_connects(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Test a repair issue points at the DNS record, until a thermostat connects."""
    issue_id = f"gateway_no_thermostat_{ENTRY_ID}"
    entry = _entry("relay")
    await _setup(hass, entry)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=local.CONNECT_GRACE + 1)
    )
    await hass.async_block_till_done()

    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {
        "hostname": "na-thermos.ojelectronics.com",
        "ip": "10.10.10.10",
        "port": "9533",
    }

    _report(entry, SERIAL, Online=True)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.usefixtures("mock_wg4_api")
async def test_no_issue_when_a_thermostat_connected(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Test there is nothing to repair once a thermostat found its way."""
    entry = _entry("relay")
    await _setup(hass, entry)

    with patch.object(
        WG4Gateway, "connected", new_callable=PropertyMock, return_value={SERIAL}
    ):
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=local.CONNECT_GRACE + 1)
        )
        await hass.async_block_till_done()

    assert not issue_registry.issues


@pytest.mark.usefixtures("mock_wg4_api")
async def test_issue_for_unexpected_certificate(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Test a repair issue tells that OJ's gateway is not trusted."""
    issue_id = f"gateway_untrusted_{ENTRY_ID}"
    entry = _entry("relay")
    await _setup(hass, entry)
    changed = _gateway(entry).on_upstream
    assert changed is not None

    changed(UpstreamStatus.UNTRUSTED)
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {
        "hostname": "na-thermos.ojelectronics.com"
    }

    changed(UpstreamStatus.CONNECTED)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    # The issue does not outlive the gateway.
    changed(UpstreamStatus.UNTRUSTED)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.usefixtures("mock_wg4_api")
async def test_diagnostics(hass: HomeAssistant) -> None:
    """Test the diagnostics describe the gateway without what it stores."""
    entry = _entry("relay")
    await _setup(hass, entry)
    _gateway(entry).profiles[SERIAL] = PROFILE

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["gateway"] == {
        "mode": "relay",
        "connected": 0,
        "relayed": 0,
        "profiles": 1,
        "upstream": None,
        "upstream_fingerprint": None,
        "cloud_error": None,
        # What happened on the gateway's connections; nothing yet.
        "history": [],
    }
    assert "user@example.com" not in str(diagnostics)
    assert PROFILE.to_dict()["support"] not in str(diagnostics)


def test_certificate_is_created_once(tmp_path: Path) -> None:
    """Test the gateway gets a certificate that only the owner can read."""
    directory = tmp_path / DOMAIN
    with patch(f"{MODULE}.local.server_ssl_context") as load:
        load_ssl_context(directory)

    certfile = directory / "gateway.crt"
    keyfile = directory / "gateway.key"
    load.assert_called_once_with(certfile, keyfile)
    assert certfile.read_text().startswith("-----BEGIN CERTIFICATE-----")
    assert keyfile.stat().st_mode & 0o777 == 0o600
    # The certificate can be loaded as the gateway's.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)

    created = certfile.read_bytes()
    with patch(f"{MODULE}.local.server_ssl_context"):
        load_ssl_context(directory)
    assert certfile.read_bytes() == created


async def test_dns_check(hass: HomeAssistant) -> None:
    """Test the check whether the gateway's name leads to Home Assistant."""
    assert await local.async_host_ip(hass) == "10.10.10.10"

    def resolves_to(address: str) -> AsyncMock:
        return AsyncMock(return_value=[(2, 1, 6, "", (address, 9533))])

    endpoint = WG4_NORTH_AMERICA
    with patch.object(hass.loop, "getaddrinfo", resolves_to("10.10.10.10")):
        assert await local.async_dns_points_here(hass, endpoint, "10.10.10.10")
    with patch.object(hass.loop, "getaddrinfo", resolves_to("52.165.43.242")):
        assert not await local.async_dns_points_here(hass, endpoint, "10.10.10.10")
    with patch.object(hass.loop, "getaddrinfo", AsyncMock(side_effect=OSError)):
        assert not await local.async_dns_points_here(hass, endpoint, "10.10.10.10")

    # Without a known address the instructions show a question mark.
    with patch(f"{MODULE}.local.async_get_source_ip", side_effect=HomeAssistantError):
        assert await local.async_host_ip(hass) == "?"


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_flow_to_relay(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, listener: AsyncMock
) -> None:
    """Test choosing the relay shows the DNS record, and warns if it is missing."""
    await _setup(hass, mock_config_entry)
    chosen = {
        "use_comfort_mode": False,
        "comfort_mode_duration": 240,
        "connection_mode": "relay",
    }

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], chosen
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "gateway"
    assert result["description_placeholders"] == {
        "hostname": "na-thermos.ojelectronics.com",
        "ip": "10.10.10.10",
        "port": "9533",
    }

    # Home Assistant does not see the record: warn once, then go on.
    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=False):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "dns_not_detected"}
        listener.assert_not_awaited()

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == chosen

    # The entry reloads, which starts the gateway.
    await hass.async_block_till_done()
    listener.assert_awaited_once()
    assert mock_config_entry.runtime_data.local.mode is GatewayMode.RELAY


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_flow_to_local_needs_a_profile(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test local only is refused until a thermostat has been relayed."""
    await _setup(hass, mock_config_entry)
    chosen = {
        "use_comfort_mode": False,
        "comfort_mode_duration": 240,
        "connection_mode": "local",
    }

    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=True):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], chosen
        )
        # The first screen says so, where another mode can be chosen.
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"
        assert result["errors"] == {"base": "no_profile"}

        # A relayed session stored a profile in the meantime.
        hass_storage[STORE_KEY] = _stored()
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], chosen
        )
        # The other thermostat has no profile yet; that is a warning.
        assert result["errors"] == {"base": "profile_missing"}
        assert result["description_placeholders"] == {"thermostats": "SecondRoom"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], chosen
        )
        assert result["step_id"] == "gateway"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == chosen


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_flow_back_to_cloud(hass: HomeAssistant) -> None:
    """Test leaving a local mode warns while the DNS record is still there."""
    entry = _entry("relay")
    await _setup(hass, entry)
    chosen = {
        "use_comfort_mode": True,
        "comfort_mode_duration": 60,
        "connection_mode": "cloud",
    }

    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], chosen
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"
        assert result["errors"] == {"base": "dns_still_local"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], chosen
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == chosen

    await hass.async_block_till_done()
    assert entry.runtime_data.local is None


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_flow_back_to_cloud_without_the_record(
    hass: HomeAssistant,
) -> None:
    """Test leaving a local mode needs no confirmation once the record is gone."""
    entry = _entry("relay")
    await _setup(hass, entry)

    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=False):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "use_comfort_mode": False,
                "comfort_mode_duration": 240,
                "connection_mode": "cloud",
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["connection_mode"] == "cloud"


@pytest.mark.usefixtures("mock_wd5_api")
async def test_options_flow_without_a_known_gateway(hass: HomeAssistant) -> None:
    """Test an account whose device gateway is not known has no connection mode."""
    mock_wd5_config_entry = MockConfigEntry(
        domain=DOMAIN, version=2, data={**WD5_DATA, "customer_id": 1}
    )
    await _setup(hass, mock_wd5_config_entry)

    result = await hass.config_entries.options.async_init(
        mock_wd5_config_entry.entry_id
    )
    schema = result["data_schema"]
    assert schema is not None
    assert "connection_mode" not in {str(key) for key in schema.schema}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"use_comfort_mode": True, "comfort_mode_duration": 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_wd5_config_entry.options == {
        "use_comfort_mode": True,
        "comfort_mode_duration": 60,
    }


def _updates(aioclient_mock: AiohttpClientMocker) -> list[dict[str, Any]]:
    """Return the bodies of the group updates sent to the cloud."""
    return [
        call[2]
        for call in aioclient_mock.mock_calls
        if call[1].path == "/api/Group/UpdateGroup"
    ]


async def test_wd5_local_only_refuses_what_only_the_cloud_sets(
    hass: HomeAssistant, mock_wd5_api: AiohttpClientMocker
) -> None:
    """Test a change the cloud would accept but never deliver is refused."""
    entry = _wd5_entry("local")
    await _setup(hass, entry)
    _report(entry, WD5_SERIAL, Online=True)
    await _deliver(hass, entry)
    coordinator = entry.runtime_data
    thermostat = coordinator.data[WD5_SERIAL]

    with pytest.raises(OJMicrolineError, match="not connected"):
        await coordinator.async_set_regulation_mode(
            thermostat, REGULATION_FROST_PROTECTION
        )
    with pytest.raises(OJMicrolineError, match="not connected"):
        await coordinator.async_set_schedule(thermostat, {})
    with pytest.raises(OJMicrolineError, match="not connected"):
        await coordinator.async_set_vacation(
            thermostat, date(2026, 12, 1), date(2026, 12, 8), enabled=False
        )
    assert not _updates(mock_wd5_api)

    # The thermostat that never connected here still reaches the cloud.
    await coordinator.async_set_regulation_mode(
        coordinator.data[WD5_OTHER], REGULATION_FROST_PROTECTION
    )
    assert len(_updates(mock_wd5_api)) == 1


async def test_wd5_group_change_starts_from_the_cloud(
    hass: HomeAssistant, mock_wd5_api: AiohttpClientMocker
) -> None:
    """Test a mode set on one thermostat does not spread over its group."""
    entry = _wd5_entry("relay")
    await _setup(hass, entry)
    _report(entry, WD5_SERIAL, Online=True, RegulationMode=REGULATION_COMFORT)
    # pylint: disable-next=protected-access
    _gateway(entry)._links[WD5_SERIAL].upstream = Mock()
    await _deliver(hass, entry)
    coordinator = entry.runtime_data
    thermostat = coordinator.data[WD5_SERIAL]
    assert thermostat.regulation_mode == REGULATION_COMFORT

    await coordinator.async_set_schedule(thermostat, {"Days": []})
    group = _updates(mock_wd5_api)[-1]["SetGroup"]
    assert group["RegulationMode"] == REGULATION_SCHEDULE
    assert group["Schedule"] == {"Days": []}


@pytest.mark.usefixtures("mock_wg4_api")
async def test_comfort_is_left_where_only_the_gateway_reaches(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Test a new temperature is manual where the gateway cannot set comfort.

    That holds for a thermostat in comfort mode already, and in relay mode
    for one that is answered locally because OJ's gateway cannot be used.
    """
    hass_storage[STORE_KEY] = _stored()
    entry = _entry("local", use_comfort_mode=True)
    await _setup(hass, entry)
    send = AsyncMock()
    _gateway(entry).set_mode = send  # type: ignore[method-assign]
    _report(entry, SERIAL, Online=True, RegulationMode=REGULATION_COMFORT)
    await _deliver(hass, entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.roomname", ATTR_TEMPERATURE: 21},
        blocking=True,
    )
    send.assert_awaited_once_with(SERIAL, REGULATION_MANUAL, 2100)


@pytest.mark.usefixtures("mock_wg4_api")
async def test_relay_without_ojs_gateway_has_no_comfort(hass: HomeAssistant) -> None:
    """Test a thermostat answered locally in relay mode is set to manual."""
    entry = _entry("relay", use_comfort_mode=True)
    await _setup(hass, entry)
    send = AsyncMock()
    _gateway(entry).set_mode = send  # type: ignore[method-assign]
    _report(entry, SERIAL, Online=True, RegulationMode=REGULATION_SCHEDULE)
    await _deliver(hass, entry)
    state = _state(hass, "climate.roomname")
    assert state.attributes["preset_modes"] == ["schedule", "manual"]

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.roomname", ATTR_TEMPERATURE: 21},
        blocking=True,
    )
    send.assert_awaited_once_with(SERIAL, REGULATION_MANUAL, 2100)


async def test_energy_usage_of_a_thermostat_elsewhere_in_local_mode(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_wg4_api: AiohttpClientMocker,
) -> None:
    """Test the cloud measures a thermostat that does not connect here."""
    hass_storage[STORE_KEY] = _stored()
    entry = _entry("local")
    await _setup(hass, entry)

    data = entry.runtime_data.data
    # The thermostat with a profile is on the gateway, and not in the cloud.
    assert data[SERIAL].energy is None
    assert data[OTHER].energy is not None
    assert _requests(mock_wg4_api, "/api/energyusage") > 0


@pytest.mark.usefixtures("mock_wg4_api")
async def test_back_on_the_cloud_forgets_what_was_stored(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Test the snapshot, with the email address, goes in cloud mode."""
    hass_storage[STORE_KEY] = _stored()
    await _setup(hass, _entry("cloud"))
    assert STORE_KEY not in hass_storage


@pytest.mark.usefixtures("mock_wg4_api")
async def test_one_gateway_per_port(hass: HomeAssistant) -> None:
    """Test a second account cannot run a gateway on the port of the first."""
    first = _entry("relay")
    await _setup(hass, first)
    second = MockConfigEntry(
        domain=DOMAIN, title="Second account", version=2, data=WG4_DATA
    )
    await _setup(hass, second)
    chosen = {
        "use_comfort_mode": False,
        "comfort_mode_duration": 240,
        "connection_mode": "relay",
    }

    result = await hass.config_entries.options.async_init(second.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], chosen
    )
    assert result["errors"] == {"base": "port_in_use"}
    assert result["description_placeholders"] == {"entry": first.title}

    # One that was set to a local mode before does not start its gateway.
    third = MockConfigEntry(
        domain=DOMAIN, version=2, data=WG4_DATA, options={"connection_mode": "relay"}
    )
    third.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(third.entry_id)
    assert third.state is ConfigEntryState.SETUP_ERROR


@pytest.mark.usefixtures("mock_wg4_api")
async def test_options_flow_keeps_the_mode_without_questions(
    hass: HomeAssistant,
) -> None:
    """Test a change of the comfort settings alone saves at once."""
    entry = _entry("relay")
    await _setup(hass, entry)
    chosen = {
        "use_comfort_mode": True,
        "comfort_mode_duration": 60,
        "connection_mode": "relay",
    }
    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=False):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], chosen
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == chosen


@pytest.mark.usefixtures("mock_wg4_api")
async def test_each_warning_is_shown_once(hass: HomeAssistant) -> None:
    """Test the warning about leaving does not skip the check of the record."""
    hass_storage_entry = _entry("local")
    await _setup(hass, hass_storage_entry)
    to_cloud = {
        "use_comfort_mode": False,
        "comfort_mode_duration": 240,
        "connection_mode": "cloud",
    }
    to_relay = {**to_cloud, "connection_mode": "relay"}

    result = await hass.config_entries.options.async_init(hass_storage_entry.entry_id)
    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], to_cloud
        )
    assert result["errors"] == {"base": "dns_still_local"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], to_relay
    )
    assert result["step_id"] == "gateway"
    with patch(f"{MODULE}.config_flow.async_dns_points_here", return_value=False):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
    assert result["errors"] == {"base": "dns_not_detected"}


def test_damaged_certificate_is_replaced(tmp_path: Path) -> None:
    """Test a certificate that cannot be loaded is created anew."""
    directory = tmp_path / DOMAIN
    directory.mkdir()
    (directory / "gateway.crt").write_text("-----BEGIN CERTIFICATE-----\n")
    (directory / "gateway.key").write_text("")

    context = load_ssl_context(directory)

    assert isinstance(context, ssl.SSLContext)
    assert (directory / "gateway.crt").read_text().count("BEGIN CERTIFICATE") == 1
    assert (directory / "gateway.key").stat().st_size > 0


@pytest.mark.usefixtures("mock_wg4_api")
async def test_certificate_that_cannot_be_made_retries_setup(
    hass: HomeAssistant,
) -> None:
    """Test an unwritable configuration directory fails the setup for now."""
    entry = _entry("relay")
    entry.add_to_hass(hass)
    with patch(
        f"{MODULE}.local._load_ssl_context", side_effect=PermissionError("read-only")
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_wg4_api")
async def test_local_client_uses_the_same_session(hass: HomeAssistant) -> None:
    """Test the client of the gateway's API takes over the HTTP session."""
    with patch(f"{MODULE}.api.async_create_clientsession") as create:
        await _setup(hass, _entry("relay"))
    create.assert_not_called()
