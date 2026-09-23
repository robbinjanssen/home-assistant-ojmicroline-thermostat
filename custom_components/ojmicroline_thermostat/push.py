"""Push updates for WD5-series thermostats.

The OJ Microline and SWATT apps receive live updates through a classic
ASP.NET SignalR persistent connection (protocol 1.3) at
``https://<host>/ocd5notification``, using the Server-Sent Events transport.
Once connected, the client sends its session ID, after which the server
pushes a JSON object with ``Thermostats``, ``Groups`` and
``ThermostatRealTimes`` whenever something changes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from ojmicroline_thermostat import WD5API, OJMicrolineError

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

HUB_PATH = "ocd5notification"
CLIENT_PROTOCOL = "1.3"
TRANSPORT = "serverSentEvents"
DEFAULT_KEEP_ALIVE_TIMEOUT = 20.0
RECONNECT_MIN_DELAY = 5
RECONNECT_MAX_DELAY = 300


class WD5PushClient:
    """Listen for push notifications from the WD5 notification hub."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        hass: HomeAssistant,
        session: ClientSession,
        api: WD5API,
        on_message: Callable[[dict[str, Any]], None],
        on_connection_change: Callable[[bool], None],
    ) -> None:
        """Initialise the push client.

        Args:
        ----
            hass: The HomeAssistant instance.
            session: The aiohttp session to use.
            api: The WD5 API object, used for its host and session ID.
            on_message: Called with every pushed message.
            on_connection_change: Called when the connection goes up or down.

        """
        self._hass = hass
        self._session = session
        self._api = api
        self._on_message = on_message
        self._on_connection_change = on_connection_change
        self._connected = False

    @property
    def _base_url(self) -> str:
        return f"https://{self._api.host}/{HUB_PATH}/"

    def start(self, entry: ConfigEntry) -> None:
        """Start listening; the task is cancelled when the entry unloads."""
        entry.async_create_background_task(
            self._hass, self._run(), f"{entry.domain} push {entry.entry_id}"
        )

    def _set_connected(self, *, connected: bool) -> None:
        if connected != self._connected:
            self._connected = connected
            self._on_connection_change(connected)

    async def _run(self) -> None:
        delay = RECONNECT_MIN_DELAY
        while True:
            try:
                await self._listen()
                delay = RECONNECT_MIN_DELAY
            except (
                ClientError,
                TimeoutError,
                OJMicrolineError,
                KeyError,
                ValueError,
            ) as err:
                _LOGGER.debug("Push connection lost: %s", err)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Unexpected error in push connection")
                delay = RECONNECT_MAX_DELAY
            finally:
                self._set_connected(connected=False)

            await asyncio.sleep(delay)

    async def _listen(self) -> None:
        """Connect to the hub and process messages until the stream ends.

        Returns early when the API session changes, so that the next
        connection registers the new session ID.
        """
        await self._api.login()
        # pylint: disable-next=protected-access
        session_id = self._api._session_id  # noqa: SLF001
        if session_id is None:
            msg = "No session ID available"
            raise OJMicrolineError(msg)

        negotiate = await self._get_json(
            "negotiate", {"clientProtocol": CLIENT_PROTOCOL}
        )
        connection = {
            "transport": TRANSPORT,
            "connectionToken": negotiate["ConnectionToken"],
            "connectionId": negotiate["ConnectionId"],
        }
        keep_alive = negotiate.get("KeepAliveTimeout") or DEFAULT_KEEP_ALIVE_TIMEOUT

        async with self._session.get(
            self._base_url + "connect",
            params=connection,
            headers={"Accept": "text/event-stream"},
            timeout=ClientTimeout(total=None, sock_read=keep_alive * 2),
        ) as response:
            response.raise_for_status()
            async for raw_line in response.content:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()

                if payload == "initialized":
                    await self._send(connection, session_id)
                    _LOGGER.debug("Push connection established")
                    self._set_connected(connected=True)
                    continue

                # pylint: disable-next=protected-access
                if self._api._session_id != session_id:  # noqa: SLF001
                    _LOGGER.debug("API session changed, reconnecting push")
                    return

                self._handle_payload(payload)

    def _handle_payload(self, payload: str) -> None:
        data = json.loads(payload)
        if not isinstance(data, dict):
            return
        # Keep-alive frames are empty objects; data frames carry "M".
        for message in data.get("M") or []:
            if isinstance(message, str):
                # E.g. '"No Way"' when the hub rejects the session ID.
                with contextlib.suppress(ValueError):
                    message = json.loads(message)  # noqa: PLW2901
            if isinstance(message, dict):
                self._on_message(message)
            else:
                _LOGGER.debug("Ignoring push message: %s", message)

    async def _get_json(self, path: str, params: dict[str, str]) -> Any:
        async with self._session.get(
            self._base_url + path, params=params, timeout=ClientTimeout(total=30)
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def _send(self, connection: dict[str, str], data: str) -> None:
        async with self._session.post(
            self._base_url + "send",
            params=connection,
            data={"data": data},
            timeout=ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
