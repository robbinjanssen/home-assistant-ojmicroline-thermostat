"""The local gateway of a WG4-series account.

In a local connection mode the thermostats connect to Home Assistant instead
of OJ's device gateway. The gateway and its API come from the library. This
module adds what Home Assistant has to keep and show: the certificate, the
stored snapshot and profiles, and the repair issues.
"""

from __future__ import annotations

import datetime
import logging
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from ojmicroline_thermostat import (
    WG4_NORTH_AMERICA,
    DeviceProfile,
    GatewayMode,
    UpstreamStatus,
    WG4Gateway,
    WG4LocalAPI,
    server_ssl_context,
)

from .const import DOMAIN

if TYPE_CHECKING:
    import ssl

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ojmicroline_thermostat import WG4API

_LOGGER = logging.getLogger(__name__)

# The device gateway of OJ that the thermostats look for.
ENDPOINT = WG4_NORTH_AMERICA

STORAGE_VERSION = 1
# The snapshot changes with almost every poll, so writing it may wait.
SNAPSHOT_SAVE_DELAY = 60
# A recorded profile is what local mode depends on; write it soon.
PROFILE_SAVE_DELAY = 1
# How long the thermostats get to connect before a repair issue points at
# the DNS record, which is almost always what is missing.
CONNECT_GRACE = 600

CERTIFICATE = "gateway.crt"
PRIVATE_KEY = "gateway.key"

ISSUE_NO_THERMOSTAT = "gateway_no_thermostat"
ISSUE_UNTRUSTED = "gateway_untrusted"


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


async def async_dns_points_here(hass: HomeAssistant, host_ip: str) -> bool:
    """Return whether Home Assistant resolves the gateway's name to itself.

    The thermostats may use another DNS server than Home Assistant does, so
    this is a hint and not proof either way.
    """
    try:
        infos = await hass.loop.getaddrinfo(
            ENDPOINT.host, ENDPOINT.port, family=socket.AF_INET
        )
    except OSError:
        return False
    return host_ip in {info[4][0] for info in infos}


async def async_has_profile(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return whether a thermostat of the entry can be answered locally."""
    if entry.state is ConfigEntryState.LOADED:
        local: LocalGateway | None = entry.runtime_data.local
        if local is not None and local.gateway.profiles:
            return True
    stored = await gateway_store(hass, entry.entry_id).async_load()
    return bool(stored and stored.get("profiles"))


def _create_certificate(certfile: Path, keyfile: Path) -> None:
    """Create a self-signed certificate; the thermostat accepts any."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ENDPOINT.host)])
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
            x509.SubjectAlternativeName([x509.DNSName(ENDPOINT.host)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    certfile.parent.mkdir(parents=True, exist_ok=True)
    # Create the key file unreadable for others before the key goes into it.
    keyfile.touch(mode=0o600)
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

    This reads and writes files, so it runs in an executor.
    """
    certfile = directory / CERTIFICATE
    keyfile = directory / PRIVATE_KEY
    if not certfile.exists() or not keyfile.exists():
        _create_certificate(certfile, keyfile)
    return server_ssl_context(certfile, keyfile)


class LocalGateway:
    """Runs the local gateway of one account, and stores what it learns."""

    gateway: WG4Gateway
    api: WG4LocalAPI

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, cloud: WG4API, mode: GatewayMode
    ) -> None:
        """Prepare a gateway for the account of the cloud API."""
        self.hass = hass
        self.mode = mode
        self._entry_id = entry.entry_id
        self._cloud = cloud
        self._store = gateway_store(hass, entry.entry_id)
        self._stored: dict[str, Any] = {"snapshot": {}, "profiles": {}}
        self._cancel_check: CALLBACK_TYPE | None = None

    async def async_start(self) -> WG4LocalAPI:
        """Load what was stored, start listening, and return the API to use.

        Raises
        ------
            OJMicrolineConnectionError: The port of the gateway is in use.

        """
        if stored := await self._store.async_load():
            self._stored = {
                "snapshot": stored.get("snapshot", {}),
                "profiles": stored.get("profiles", {}),
            }
        profiles: dict[str, DeviceProfile] = {}
        for serial, data in self._stored["profiles"].items():
            try:
                profiles[serial] = DeviceProfile.from_dict(data)
            except ValueError:
                # The thermostat is relayed again, which records a new one.
                _LOGGER.warning("Ignoring a stored profile that is damaged")

        context = await self.hass.async_add_executor_job(
            _load_ssl_context, Path(self.hass.config.path(DOMAIN))
        )
        self.gateway = WG4Gateway(
            context, mode=self.mode, endpoint=ENDPOINT, profiles=profiles
        )
        self.gateway.on_profile = self._async_profile_recorded
        self.gateway.on_upstream = self._async_upstream_changed
        self.api = WG4LocalAPI(
            self._cloud,
            self.gateway,
            snapshot=self._stored["snapshot"],
            on_snapshot=self._async_snapshot_changed,
        )
        # The API listens to what the thermostats report. Listen along, to
        # know when the first thermostat has found its way here.
        report = self.gateway.on_state

        def on_state(serial: str, fields: dict[str, Any]) -> None:
            if report is not None:
                report(serial, fields)
            if fields.get("Online"):
                ir.async_delete_issue(
                    self.hass, DOMAIN, self._issue_id(ISSUE_NO_THERMOSTAT)
                )

        self.gateway.on_state = on_state
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
            translation_placeholders={"hostname": ENDPOINT.host},
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
                "hostname": ENDPOINT.host,
                "ip": await async_host_ip(self.hass),
                "port": str(ENDPOINT.port),
            },
        )
