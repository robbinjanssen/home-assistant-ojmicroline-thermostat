"""The local gateway of a WG4-series or WD5-series account.

In a local connection mode the thermostats connect to Home Assistant instead
of OJ's device gateway. The gateway and its API come from the library. This
module adds what Home Assistant has to keep and show: the certificate, the
stored snapshot and profiles, and the repair issues.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import json
import logging
import socket
import ssl
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from homeassistant.components.network import async_get_adapters, async_get_source_ip
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_USERNAME
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from ojmicroline_thermostat import (
    WD5_OJ001,
    WD5_R1099,
    WD5_SL003,
    WG4_NORTH_AMERICA,
    WG4API,
    DeviceProfile,
    GatewayEndpoint,
    GatewayMode,
    OJMicrolineError,
    UpstreamStatus,
    WD5Gateway,
    WD5LocalAPI,
    WG4Gateway,
    WG4LocalAPI,
    server_ssl_context,
)

from .api import api_from_config_entry_data
from .const import (
    CONF_APPLICATION,
    CONF_CONNECTION_MODE,
    CONF_CUSTOMER_ID,
    CONF_MODEL,
    CONNECTION_CLOUD,
    DEFAULT_WD5_CUSTOMER_ID,
    DEFAULT_WG4_APPLICATION,
    DOMAIN,
    MODEL_WD5_SERIES,
    MODEL_WG4_SERIES,
)
from .helpers import thermostat_name

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ojmicroline_thermostat import WD5API

_LOGGER = logging.getLogger(__name__)

# The device gateway WD5-series thermostats look for, by the customer ID of
# their brand: the SWATT app, Schlüter in Europe, and the OJ Microline app.
WD5_ENDPOINTS = {99: WD5_R1099, 3: WD5_SL003, 1: WD5_OJ001}
# The device gateway WG4-series thermostats look for, by the application code
# of their app: mythermostat.info, where the gateway ran against a real
# thermostat, and Schlüter in North America, where schluter-local comes from.
# Where the thermostats of other apps, such as Danfoss LX, look is not known.
WG4_ENDPOINTS = {DEFAULT_WG4_APPLICATION: WG4_NORTH_AMERICA, 7: WG4_NORTH_AMERICA}
# The name in the certificate of the gateway. A thermostat does not read it.
CERTIFICATE_NAME = "ojmicroline-thermostat.local"

STORAGE_VERSION = 1
# The snapshot changes with almost every poll, so writing it may wait.
SNAPSHOT_SAVE_DELAY = 60
# A recorded profile is what local mode depends on; write it soon.
PROFILE_SAVE_DELAY = 1
# How long the thermostats get to connect before a repair issue points at
# the DNS record, which is almost always what is missing.
CONNECT_GRACE = 600

# Where the history of a stopped gateway is kept, by entry ID, so the
# diagnostics after a reload still show what happened before it. It does not
# survive a restart of Home Assistant.
PREVIOUS_HISTORY = f"{DOMAIN}_previous_history"

CERTIFICATE = "gateway.crt"
PRIVATE_KEY = "gateway.key"

ISSUE_NO_THERMOSTAT = "gateway_no_thermostat"
ISSUE_UNTRUSTED = "gateway_untrusted"


def endpoint_for(data: Mapping[str, Any]) -> GatewayEndpoint | None:
    """Return the device gateway of OJ that the thermostats of an account look for.

    None means that a local connection is not possible: the series has no
    local gateway, or the gateway of the brand is not known.
    """
    model = data.get(CONF_MODEL)
    if model == MODEL_WG4_SERIES:
        return WG4_ENDPOINTS.get(data.get(CONF_APPLICATION, DEFAULT_WG4_APPLICATION))
    if model == MODEL_WD5_SERIES:
        return WD5_ENDPOINTS.get(data.get(CONF_CUSTOMER_ID, DEFAULT_WD5_CUSTOMER_ID))
    return None


def local_entries_on_port(
    hass: HomeAssistant, port: int, exclude: str
) -> list[ConfigEntry]:
    """Return the other entries that run a gateway on a port.

    Only one gateway can listen on a port, and every account of a series
    uses the same one.
    """
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != exclude
        and entry.options.get(CONF_CONNECTION_MODE, CONNECTION_CLOUD)
        != CONNECTION_CLOUD
        and (endpoint := endpoint_for(entry.data)) is not None
        and endpoint.port == port
    ]


def gateway_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return where the snapshot and profiles of a config entry are stored."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.gateway")


async def async_host_ip(hass: HomeAssistant) -> str:
    """Return the address the thermostats have to reach Home Assistant on."""
    try:
        return await async_get_source_ip(hass)
    except HomeAssistantError, OSError:
        # Only used in instructions; a question mark shows it is unknown.
        return "?"


async def async_host_ips(hass: HomeAssistant) -> set[str]:
    """Return the IPv4 addresses of Home Assistant a thermostat may use.

    The gateway listens on all of them, so a DNS record may point at any:
    on a machine with a leg on the thermostats' own network, that address
    keeps their connection off the router. Loopback and link-local
    addresses are left out, as no thermostat reaches those. The adapters
    are the ones Home Assistant read when it started.
    """
    try:
        adapters = await async_get_adapters(hass)
    except HomeAssistantError, OSError:
        # Without the adapters the suggested address is still checked.
        adapters = []
    addresses = {ipv4["address"] for adapter in adapters for ipv4 in adapter["ipv4"]}
    if (host_ip := await async_host_ip(hass)) != "?":
        addresses.add(host_ip)
    return {
        address
        for address in addresses
        if not (ip := ipaddress.ip_address(address)).is_loopback
        and not ip.is_link_local
    }


async def async_dns_points_here(hass: HomeAssistant, endpoint: GatewayEndpoint) -> bool:
    """Return whether Home Assistant resolves the gateway's name to itself.

    The thermostats may use another DNS server than Home Assistant does, so
    this is a hint and not proof either way.
    """
    try:
        infos = await hass.loop.getaddrinfo(
            endpoint.host, endpoint.port, family=socket.AF_INET
        )
    except OSError:
        return False
    return not (await async_host_ips(hass)).isdisjoint(info[4][0] for info in infos)


async def async_profiles(
    hass: HomeAssistant, entry: ConfigEntry
) -> tuple[set[str], dict[str, str]] | None:
    """Return which thermostats of a WG4-series entry can be answered locally.

    A WG4-series thermostat needs a profile for that, which is recorded while
    it is relayed. A WD5-series thermostat needs nothing, for which this
    returns None.

    Returns
    -------
        The serial numbers with a profile, and the name of every thermostat
        of the account by serial number, as far as they are known.

    """
    if entry.data.get(CONF_MODEL) != MODEL_WG4_SERIES:
        return None
    stored = _stored_for(
        _account(entry.data), await gateway_store(hass, entry.entry_id).async_load()
    )
    # A profile that cannot be used does not answer a thermostat.
    profiles = {
        serial
        for serial, data in stored["profiles"].items()
        if _profile(data) is not None
    }
    names = {serial: serial for serial in stored["snapshot"]}
    if entry.state is ConfigEntryState.LOADED:
        coordinator = entry.runtime_data
        if coordinator.local is not None:
            profiles |= set(coordinator.local.profiles)
        names |= {
            serial: thermostat_name(thermostat)
            for serial, thermostat in (coordinator.data or {}).items()
        }
    return profiles, names


def _account(data: Mapping[str, Any]) -> str:
    """Return what tells the account of an entry apart, without naming it.

    What is stored for one account is of no use to another: after a
    reconfigure to another account or brand it is left behind. The settings
    count as they are used: a reconfigure writes out the defaults that an
    older entry leaves to the integration, which makes it no other account.
    """
    endpoint = endpoint_for(data)
    identity = json.dumps(
        [
            data.get(CONF_MODEL),
            api_from_config_entry_data(data).host,
            data.get(CONF_USERNAME),
            None if endpoint is None else endpoint.host,
        ]
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _stored_for(account: str, stored: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return what a store holds for an account: nothing of another account.

    A store without an account is from before the account was kept, and
    belongs to the entry.
    """
    if not stored or stored.get("account", account) != account:
        stored = {}
    return {
        "account": account,
        # The JSON of each thermostat, as the cloud API returned it last.
        "snapshot": dict(stored.get("snapshot", {})),
        # The recorded profile of each WG4-series thermostat.
        "profiles": dict(stored.get("profiles", {})),
        # The thermostats that connected to the gateway before.
        "known": list(stored.get("known", [])),
    }


def _profile(data: Any) -> DeviceProfile | None:
    """Read a stored profile; None if it cannot be used."""
    try:
        return DeviceProfile.from_dict(data)
    except KeyError, TypeError, ValueError:
        return None


async def async_forget(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the stored snapshot and profiles of an entry.

    The snapshot holds the email address of the account, so it does not stay
    behind once the entry is back on the cloud.
    """
    await gateway_store(hass, entry_id).async_remove()


def _create_certificate(certfile: Path, keyfile: Path) -> None:
    """Create a self-signed certificate; the thermostat accepts any."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CERTIFICATE_NAME)])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(CERTIFICATE_NAME)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certfile.parent.mkdir(parents=True, exist_ok=True)
    # Create the key file unreadable for others before the key goes into it.
    # A file that was there keeps its mode on touch(), so set it as well.
    keyfile.touch(mode=0o600)
    keyfile.chmod(0o600)
    keyfile.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def _load_ssl_context(directory: Path) -> ssl.SSLContext:
    """Load the gateway's certificate, creating it on first use.

    A certificate that cannot be loaded, for example after Home Assistant
    stopped while it was written, is replaced: the thermostats accept any.
    This reads and writes files, so it runs in an executor.

    Raises
    ------
        OSError: The files cannot be written.
        ssl.SSLError: The new certificate cannot be loaded either.

    """
    certfile = directory / CERTIFICATE
    keyfile = directory / PRIVATE_KEY
    if certfile.exists() and keyfile.exists():
        try:
            return server_ssl_context(certfile, keyfile)
        except (OSError, ssl.SSLError) as error:
            _LOGGER.warning("Replacing the certificate of the gateway: %s", error)
    _create_certificate(certfile, keyfile)
    return server_ssl_context(certfile, keyfile)


class LocalGateway:
    """Runs the local gateway of one account, and stores what it learns."""

    gateway: WG4Gateway | WD5Gateway
    api: WG4LocalAPI | WD5LocalAPI

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cloud: WG4API | WD5API,
        endpoint: GatewayEndpoint,
        mode: GatewayMode,
    ) -> None:
        """Prepare a gateway for the account of the cloud API."""
        self.hass = hass
        self.mode = mode
        self.endpoint = endpoint
        self._entry_id = entry.entry_id
        self._cloud = cloud
        self._store = gateway_store(hass, entry.entry_id)
        self._account = _account(entry.data)
        self._stored = _stored_for(self._account, None)
        self._cancel_check: CALLBACK_TYPE | None = None

    @property
    def previous_history(self) -> list[str]:
        """Return the history of the gateway before the last reload."""
        kept: dict[str, list[str]] = self.hass.data.get(PREVIOUS_HISTORY, {})
        return kept.get(self._entry_id, [])

    @property
    def profiles(self) -> dict[str, DeviceProfile]:
        """Return the recorded profiles; only WG4-series thermostats have one."""
        return self.gateway.profiles if isinstance(self.gateway, WG4Gateway) else {}

    async def async_start(self) -> WG4LocalAPI | WD5LocalAPI:
        """Load what was stored, start listening, and return the API to use.

        Raises
        ------
            OJMicrolineConnectionError: The port of the gateway is in use.
            OJMicrolineError: The certificate of the gateway cannot be made.

        """
        self._stored = _stored_for(self._account, await self._store.async_load())
        profiles: dict[str, DeviceProfile] = {}
        for serial, data in list(self._stored["profiles"].items()):
            profile = _profile(data)
            if profile is None:
                # The thermostat is relayed again, which records a new one.
                # Until then it counts as a thermostat without a profile.
                _LOGGER.warning("Removing a stored profile that is damaged")
                del self._stored["profiles"][serial]
                self._store.async_delay_save(self._data_to_save, PROFILE_SAVE_DELAY)
                continue
            profiles[serial] = profile

        try:
            context = await self.hass.async_add_executor_job(
                _load_ssl_context, Path(self.hass.config.path(DOMAIN))
            )
        except (OSError, ssl.SSLError) as error:
            msg = f"The certificate of the gateway cannot be made: {error}"
            raise OJMicrolineError(msg) from error
        if isinstance(self._cloud, WG4API):
            wg4 = WG4Gateway(
                context, mode=self.mode, endpoint=self.endpoint, profiles=profiles
            )
            wg4.on_profile = self._async_profile_recorded
            self.gateway = wg4
            self.api = WG4LocalAPI(
                self._cloud,
                wg4,
                snapshot=self._stored["snapshot"],
                on_snapshot=self._async_snapshot_changed,
                known=self._stored["known"],
            )
        else:
            wd5 = WD5Gateway(context, mode=self.mode, endpoint=self.endpoint)
            self.gateway = wd5
            self.api = WD5LocalAPI(
                self._cloud,
                wd5,
                snapshot=self._stored["snapshot"],
                on_snapshot=self._async_snapshot_changed,
                known=self._stored["known"],
            )
        self.gateway.on_upstream = self._async_upstream_changed
        self.gateway.on_connected = self._async_connected
        await self.gateway.start()
        self._cancel_check = async_call_later(
            self.hass, CONNECT_GRACE, self._async_check_connected
        )
        return self.api

    async def async_stop(self) -> None:
        """Stop listening, and write what was learned."""
        if self._cancel_check is not None:
            self._cancel_check()
            self._cancel_check = None
        for issue in (ISSUE_NO_THERMOSTAT, ISSUE_UNTRUSTED):
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(issue))
        await self.gateway.stop()
        self.hass.data.setdefault(PREVIOUS_HISTORY, {})[self._entry_id] = list(
            self.gateway.history
        )
        await self._store.async_save(self._stored)

    def _issue_id(self, issue: str) -> str:
        return f"{issue}_{self._entry_id}"

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return self._stored

    @callback
    def _async_snapshot_changed(self, snapshot: dict[str, dict[str, Any]]) -> None:
        self._stored["snapshot"] = snapshot
        self._store.async_delay_save(self._data_to_save, SNAPSHOT_SAVE_DELAY)

    @callback
    def _async_connected(self, serial: str) -> None:
        """Remember a thermostat that found its way to the gateway.

        In local only such a thermostat does not reach the cloud, which has
        to be known after a restart too, before it connects again.
        """
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(ISSUE_NO_THERMOSTAT))
        if serial not in self._stored["known"]:
            # The API keeps them; this only stores what it knows.
            self._stored["known"] = sorted({*self.api.known, serial})
            self._store.async_delay_save(self._data_to_save, PROFILE_SAVE_DELAY)

    @callback
    def _async_profile_recorded(self, serial: str, profile: DeviceProfile) -> None:
        self._stored["profiles"][serial] = profile.to_dict()
        self._store.async_delay_save(self._data_to_save, PROFILE_SAVE_DELAY)

    @callback
    def _async_upstream_changed(self, status: UpstreamStatus) -> None:
        """Tell the user when OJ's gateway is not the one that is expected."""
        if status is not UpstreamStatus.UNTRUSTED:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(ISSUE_UNTRUSTED))
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(ISSUE_UNTRUSTED),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_UNTRUSTED,
            translation_placeholders={"hostname": self.endpoint.host},
        )

    async def _async_check_connected(self, _now: datetime.datetime) -> None:
        """Point at the DNS record if no thermostat has connected yet."""
        self._cancel_check = None
        if self.gateway.connected:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(ISSUE_NO_THERMOSTAT),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_NO_THERMOSTAT,
            translation_placeholders={
                "hostname": self.endpoint.host,
                "ip": await async_host_ip(self.hass),
                "port": str(self.endpoint.port),
            },
        )
