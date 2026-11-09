"""WG4 local transport, verified with firmware 1012M201.

The cloud is used once to seed device metadata. Subsequent starts and all
controls use the LAN gateway and saved metadata, without a cloud request.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ojmicroline_thermostat import OJMicrolineError, Thermostat

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ojmicroline_thermostat import WG4API, OJMicroline

from .const import DOMAIN
from .local_cert import async_ensure_cert
from .local_gateway import LocalGateway
from .local_profile import async_load_profile


class WG4LocalTransport:
    """Serve an account through the local device gateway."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        model_api: WG4API,
        cloud_api: OJMicroline,
        on_update: Callable[[Thermostat], None],
    ) -> None:
        """Retain account metadata and the update callback."""
        self.hass = hass
        self._entry_id = entry.entry_id
        self._model_api = model_api
        self._cloud_api = cloud_api
        self._on_update = on_update
        self._store: Store[dict[str, dict[str, Any]]] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.local_seed"
        )
        self._seed: dict[str, dict[str, Any]] = {}
        self._live: dict[str, dict[str, Any]] = {}
        self.gateway: LocalGateway | None = None
        self._lock = asyncio.Lock()

    async def _start(self) -> None:
        async with self._lock:
            if self.gateway is not None:
                return
            try:
                profile = await async_load_profile(self.hass, self._entry_id)
            except ValueError as err:
                raise OJMicrolineError(str(err)) from err
            self._seed = (await self._store.async_load()) or {}
            if not self._seed:
                async with asyncio.timeout(30):
                    await self._cloud_api.login()
                    raw = await self._model_api.request(
                        self._model_api.get_thermostats_path,
                        method="GET",
                        # The library exposes session-aware calls this way.
                        # pylint: disable-next=protected-access
                        params={"sessionid": self._model_api._session_id},  # noqa: SLF001 - library session API
                    )
                self._seed = {
                    str(t["SerialNumber"]): t
                    for group in raw.get("Groups", [])
                    for t in group.get("Thermostats", [])
                    if t
                }
            expected = profile["serial_sha256"]
            if len(self._seed) != 1 or any(
                hashlib.sha256(serial.encode()).hexdigest() != expected
                or data.get("SWVersion") != profile["firmware"]
                for serial, data in self._seed.items()
            ):
                msg = "The captured local profile does not match this thermostat."
                raise OJMicrolineError(msg)
            await self._store.async_save(self._seed)
            cert, key = await async_ensure_cert(self.hass)
            gateway = LocalGateway(
                cert,
                key,
                on_state=self._on_state,
                allowed_serials=set(self._seed),
                configuration_frame=bytes.fromhex(profile["configuration"]),
                support_frame=bytes.fromhex(profile["support"]),
            )
            try:
                await gateway.start(self.hass)
            except OSError as err:
                await gateway.stop()
                msg = f"Unable to start local gateway on port 9533: {err}"
                raise OJMicrolineError(msg) from err
            self.gateway = gateway

    def _resource(self, serial: str) -> Thermostat:
        data = {**self._seed[serial], "Online": False, **self._live.get(serial, {})}
        resource = Thermostat.from_wg4_json(data)
        resource.supported_regulation_modes = [1, 3]
        resource.energy = None
        resource.energy_price = None
        return resource

    def _on_state(self, serial: str, fields: dict[str, Any]) -> None:
        if serial not in self._seed:
            return
        self._live.setdefault(serial, {}).update(fields)
        self._on_update(self._resource(serial))

    async def async_get_thermostats(self) -> list[Thermostat]:
        """Return local state and cached metadata; start the listener once."""
        await self._start()
        return [self._resource(serial) for serial in self._seed]

    async def async_set_mode(
        self, thermostat: Thermostat, mode: int, temperature: int | None
    ) -> None:
        """Send a bounded command only to a connected, initialized device."""
        gateway = self.gateway
        serial = thermostat.serial_number
        if gateway is None or serial not in gateway.connected_serials:
            msg = "The thermostat is not connected to the local gateway."
            raise OJMicrolineError(msg)
        if mode not in (1, 3):
            msg = "Local control currently supports schedule and manual mode."
            raise OJMicrolineError(msg)
        if (
            temperature is not None
            and not thermostat.min_temperature
            <= temperature
            <= thermostat.max_temperature
        ):
            msg = "The temperature is outside the thermostat's configured limits."
            raise OJMicrolineError(msg)
        if not gateway.has_command_template(serial):
            msg = "Waiting for the thermostat's state and schedule upload."
            raise OJMicrolineError(msg)
        await gateway.queue_set(
            serial, mode, None if temperature is None else temperature * 2
        )
        if gateway.cancel_pending(serial):
            msg = "The local command could not be sent."
            raise OJMicrolineError(msg)
        try:
            async with asyncio.timeout(10):
                while gateway.is_waiting_for_ack(serial):
                    if serial not in gateway.connected_serials:
                        msg = "The thermostat disconnected before acknowledging "
                        msg += "the command."
                        raise OJMicrolineError(msg)
                    await asyncio.sleep(0.1)
        except TimeoutError as err:
            msg = "The thermostat did not acknowledge the local command."
            raise OJMicrolineError(msg) from err

    async def async_stop(self) -> None:
        """Close every device connection and release the listening port."""
        if self.gateway is not None:
            await self.gateway.stop()
            self.gateway = None
