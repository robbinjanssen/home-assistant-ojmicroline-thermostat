"""Local-only WG4 device gateway, adapted from peskyAdmin/schluter-local.

The gateway accepts only registered thermostats and reuses configuration and
support responses captured from that device's original server connection.
State and schedule templates are always uploaded fresh by the thermostat.
See LOCAL_GATEWAY_LICENSE for the original author's MIT license.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .local_const import (
    DEVICE_TEMP_SCALE,
    EPOCH_2000,
    GATEWAY_PORT,
    MODE_COMFORT,
    MODE_MANUAL,
    MODE_SCHEDULE,
    MODE_VACATION,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# A decoded protobuf message: field number -> values, each an int (varint) or
# bytes (length-delimited, or a raw fixed-width field).
type Fields = dict[int, list[Any]]

# The thermostat sends a telemetry heartbeat every minute. If nothing arrives for
# three of them the link is dead (power cut, Wi-Fi drop), so close it and mark
# the thermostat offline instead of trusting a half-open TCP connection.
DEVICE_IDLE_TIMEOUT = 180
# Real frames are under 1 KB; refuse anything absurd from a stray LAN client.
MAX_FRAME = 64 * 1024

# The state (field 9) keeps each hold's setpoint (Celsius x200, in field 1) in a
# sub-message of its own: 9.4 for a temporary hold, with the hold's end time in
# 9.4.2, and 9.5 for a permanent hold. A command for a hold has to write that
# hold's sub-message; the thermostat ignores the other one.
_HOLD_FIELD = {MODE_COMFORT: 4, MODE_MANUAL: 5}
# The cloud API field that carries the same setpoint.
_HOLD_CLOUD_FIELD = {4: "ComfortTemperature", 5: "ManualTemperature"}
_MODE_NAMES = {
    MODE_SCHEDULE: "schedule",
    MODE_COMFORT: "temporary hold",
    MODE_MANUAL: "permanent hold",
    MODE_VACATION: "vacation",
}


# --- protobuf helpers -------------------------------------------------------
def uvarint(b: bytes, i: int) -> tuple[int, int]:
    """Read one bounded protobuf unsigned varint and its next offset."""
    shift = result = 0
    while True:
        if i >= len(b) or shift >= 70:
            msg = "Truncated or oversized protobuf varint"
            raise ValueError(msg)
        x = b[i]
        i += 1
        result |= (x & 0x7F) << shift
        shift += 7
        if not x & 0x80:
            return result, i


def wvarint(v: int) -> bytes:
    """Encode a nonnegative protobuf varint."""
    if v < 0:
        msg = "A protobuf unsigned varint cannot be negative"
        raise ValueError(msg)
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def parse(b: bytes) -> Fields:
    """Field number -> list of values (int for varint, bytes for length-delimited)."""
    i = 0
    out: Fields = {}
    while i < len(b):
        tag_val, i = uvarint(b, i)
        field = tag_val >> 3
        if not field:
            msg = "Invalid protobuf field zero"
            raise ValueError(msg)
        wire = tag_val & 7
        value: int | bytes
        if wire == 0:
            value, i = uvarint(b, i)
        elif wire == 2:
            ln, i = uvarint(b, i)
            value = b[i : i + ln]
            i += ln
        elif wire == 5:
            value = b[i : i + 4]
            i += 4
        elif wire == 1:
            value = b[i : i + 8]
            i += 8
        else:
            msg = "Unsupported protobuf wire type"
            raise ValueError(msg)
        if i > len(b):
            msg = "Truncated protobuf field"
            raise ValueError(msg)
        out.setdefault(field, []).append(value)
    return out


def _frame(body: bytes) -> bytes:
    """Wrap a protobuf body in its 0x08<len> frame prefix."""
    return b"\x08" + wvarint(len(body)) + body


def _tag(field: int, wire: int) -> bytes:
    return wvarint(field << 3 | wire)


def _encode(field: int, value: int | bytes) -> bytes:
    """Encode one field as a varint or a length-delimited value.

    State messages only use those two wire types, so re-encoding a parsed one
    gives back the same bytes.
    """
    if isinstance(value, int):
        return _tag(field, 0) + wvarint(value)
    return _tag(field, 2) + wvarint(len(value)) + value


def _with_varint(msg: bytes, field: int, value: int) -> bytes:
    """Return msg with varint field set to value and every other field kept."""
    parse(msg)
    chunks = []
    offset = 0
    replaced = False
    while offset < len(msg):
        start = offset
        tag, offset = uvarint(msg, offset)
        wire = tag & 7
        if wire == 0:
            _, offset = uvarint(msg, offset)
        elif wire == 2:
            length, offset = uvarint(msg, offset)
            offset += length
        else:
            offset += 4 if wire == 5 else 8
        if tag >> 3 == field and not replaced:
            chunks.append(_encode(field, value))
            replaced = True
        else:
            chunks.append(msg[start:offset])
    if not replaced:
        chunks.append(_encode(field, value))
    return b"".join(chunks)


def _server_time() -> int:
    return int(time.time()) - EPOCH_2000


def _login_ack(seq: int) -> bytes:
    inner = _tag(1, 0) + wvarint(_server_time())
    body = (
        _tag(1, 0)
        + wvarint(seq)
        + _tag(3, 0)
        + wvarint(1)
        + _tag(4, 0)
        + wvarint(1)
        + _tag(12, 2)
        + wvarint(len(inner))
        + inner
    )
    return _frame(body)


def _ack(seq: int) -> bytes:
    return _frame(_tag(1, 0) + wvarint(seq) + _tag(3, 0) + wvarint(1))


def _login_serial(top: Fields) -> str | None:
    if 6 not in top:
        return None
    f6 = parse(top[6][0])
    value = f6.get(2, [b""])[0]
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)


def _x100(x200: int) -> int:
    """Device setpoint (Celsius x200) to the cloud's Celsius x100."""
    return round(x200 / DEVICE_TEMP_SCALE * 100)


def _hold_setpoints(st: Fields) -> dict[int, int]:
    """Each hold's stored setpoint (Celsius x200), keyed by its sub-message."""
    out: dict[int, int] = {}
    for sub in (4, 5):
        raw = st.get(sub, [None])[0]
        if isinstance(raw, bytes):
            value = parse(raw).get(1, [None])[0]
            if isinstance(value, int):
                out[sub] = value
    return out


def _decode_state(body: bytes) -> dict[str, Any]:
    """Pull mode/setpoints/room out of a state frame into cloud field names."""
    top = parse(body)
    fields: dict[str, Any] = {}
    if 9 in top:
        st = parse(top[9][0])
        mode = st.get(2, [None])[0]
        if mode is not None:
            fields["RegulationMode"] = mode
        holds = _hold_setpoints(st)
        for sub, x200 in holds.items():
            fields[_HOLD_CLOUD_FIELD[sub]] = _x100(x200)
        hold = _HOLD_FIELD.get(mode) if isinstance(mode, int) else None
        if hold in holds:
            fields["SetPointTemp"] = _x100(holds[hold])
    if 7 in top:
        di = parse(top[7][0])
        if 2 in di and isinstance(di[2][0], bytes):
            fields["Room"] = di[2][0].decode(errors="replace")
        # 7.9 is the setpoint the thermostat is aiming for right now, in any mode.
        if 9 in di and isinstance(di[9][0], int):
            fields["SetPointTemp"] = _x100(di[9][0])
    return fields


def _decode_telemetry(f15: bytes) -> dict[str, Any]:
    """Pull current temperature and the live heating flag from a telemetry frame.

    Field 1 is the current floor temperature (Celsius x100, same scale the cloud
    uses). Field 2 is 1 while the floor is drawing power and 0 while idle; it
    tracks the relay exactly, confirmed against a heat/stop capture.
    """
    tele = parse(f15)
    fields: dict[str, Any] = {}
    if 1 in tele:
        fields["Temperature"] = tele[1][0]
    if 2 in tele:
        fields["Heating"] = bool(tele[2][0])
    return fields


def _temp(x200: int) -> str:
    """Celsius x200 as readable Celsius and Fahrenheit, for debug logs."""
    celsius = x200 / DEVICE_TEMP_SCALE
    return f"{celsius:.2f}C/{celsius * 9 / 5 + 32:.1f}F"


def _when(seconds: int) -> str:
    """Format a device timestamp as UTC for debug logs."""
    return datetime.fromtimestamp(seconds + EPOCH_2000, UTC).strftime(
        "%Y-%m-%d %H:%M:%SZ"
    )


def _brief(value: int | bytes) -> str:
    """Describe an uninterpreted field for debug logs."""
    if isinstance(value, int):
        return str(value)
    return (
        "{"
        + ", ".join(
            f"{number}: {v if isinstance(v, int) else v.hex()}"
            for number, values in parse(value).items()
            for v in values
        )
        + "}"
    )


def _describe(top: Fields) -> str:
    """One-line summary of a frame for debug logs; never includes the login."""
    parts = [
        f"seq={top.get(1, [None])[0]}",
        "fields=" + ",".join(map(str, sorted(top))),
    ]
    if 2 in top:
        parts.append(f"kind={top[2][0]}")
    if 9 in top:
        st = parse(top[9][0])
        mode = st.get(2, [None])[0]
        parts.append(f"mode={mode} ({_MODE_NAMES.get(mode, 'unknown')})")
        holds = _hold_setpoints(st)
        if 4 in holds:
            parts.append(f"temporary={_temp(holds[4])}")
            until = parse(st[4][0]).get(2, [None])[0]
            if isinstance(until, int):
                parts.append(f"until={_when(until)}")
        if 5 in holds:
            parts.append(f"permanent={_temp(holds[5])}")
        parts.extend(
            f"9.{number}={_brief(st[number][0])}"
            for number in sorted(st)
            if number not in (1, 2, 4, 5)
        )
    if 7 in top:
        target = parse(top[7][0]).get(9, [None])[0]
        if isinstance(target, int):
            parts.append(f"target={_temp(target)}")
    if 15 in top:
        tele = parse(top[15][0])
        if isinstance(floor := tele.get(1, [None])[0], int):
            parts.append(f"floor={_temp(floor * 2)}")
        if 2 in tele:
            parts.append(f"heating={tele[2][0]}")
    return " ".join(parts)


class LocalGateway:
    """Runs the TLS gateway the thermostats connect to.

    Each thermostat holds its own connection, so every per-device fact (its
    serial, its writer, its last schedule and state frames) is keyed by serial
    and several thermostats can share one gateway.
    """

    # Explicit configuration keeps private device responses mandatory.
    # pylint: disable-next=too-many-arguments
    def __init__(  # noqa: PLR0913 - explicit transport settings
        self,
        certfile: str,
        keyfile: str,
        *,
        on_state: Callable[[str, dict[str, Any]], None],
        port: int = GATEWAY_PORT,
        allowed_serials: set[str],
        configuration_frame: bytes,
        support_frame: bytes,
    ) -> None:
        """Set up the certificate, account allowlist, and captured responses."""
        self._allowed_serials = allowed_serials
        self._configuration_frame = configuration_frame
        self._support_frame = support_frame
        self._certfile = certfile
        self._keyfile = keyfile
        self._port = port
        self.on_state = on_state
        self._server: asyncio.Server | None = None
        self._server_ctx: ssl.SSLContext | None = None
        self._conns: set[asyncio.StreamWriter] = set()  # every open device link
        self._writers: dict[str, asyncio.StreamWriter] = {}  # active link per serial
        self._sched: dict[str, bytes] = {}  # last schedule (f8) per serial
        self._state_raw: dict[str, bytes] = {}  # last state (f9) per serial
        self._desired: dict[str, tuple[int, int | None]] = {}  # pending set
        self._unacked: dict[str, int] = {}  # seq of the last command sent per serial
        self._seq = 100

    @property
    def connected_serials(self) -> set[str]:
        """Serials of thermostats connected right now."""
        return set(self._writers)

    # --- lifecycle ----------------------------------------------------------
    def _build_contexts(self) -> None:
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            server_ctx.set_ciphers(
                "AES256-SHA256:AES128-SHA256:AES256-SHA:AES128-SHA:DEFAULT"
            )
        except ssl.SSLError:  # pragma: no cover - depends on the OpenSSL build
            server_ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        server_ctx.load_cert_chain(self._certfile, self._keyfile)
        self._server_ctx = server_ctx

    async def start(self, hass: HomeAssistant) -> None:
        """Start the local TLS listener on the thermostat's fixed port."""
        await hass.async_add_executor_job(self._build_contexts)
        self._server = await asyncio.start_server(
            self._handle,
            "0.0.0.0",  # noqa: S104 - thermostat LAN listener
            self._port,
            ssl=self._server_ctx,
        )
        _LOGGER.info(
            "WG4 local gateway listening on port %s; waiting for "
            "the thermostat to connect",
            self._port,
        )

    async def stop(self) -> None:
        """Close device connections and release the listening port."""
        for writer in list(self._conns):
            writer.close()
        self._conns.clear()
        self._writers.clear()
        if self._server is not None:
            self._server.close()
            with suppress(TimeoutError, OSError):
                await asyncio.wait_for(self._server.wait_closed(), 5)
            self._server = None

    def has_command_template(self, serial: str) -> bool:
        """Return whether this device uploaded both its state and schedule."""
        return serial in self._state_raw and serial in self._sched

    def cancel_pending(self, serial: str) -> bool:
        """Remove an unsent command and report whether it was still pending."""
        return self._desired.pop(serial, None) is not None

    def is_waiting_for_ack(self, serial: str) -> bool:
        """Return whether the most recent command still needs acknowledgement."""
        return serial in self._unacked

    def schedule_template(self, serial: str) -> bytes | None:
        """Return the most recently uploaded schedule, never an optimistic copy."""
        return self._sched.get(serial)

    def request_schedule_readback(self, serial: str) -> None:
        """Reconnect the device so it uploads its stored weekly schedule."""
        if writer := self._writers.get(serial):
            writer.close()

    async def send_schedule(self, serial: str, schedule: bytes) -> None:
        """Send an edited schedule while preserving the thermostat's mode/state."""
        writer = self._writers.get(serial)
        state = self._state_raw.get(serial)
        if writer is None or state is None or serial not in self._sched:
            msg = "Waiting for a connected thermostat and fresh schedule/state."
            raise ValueError(msg)
        seq = self._next_seq()
        timestamp = _server_time()
        body = (
            _encode(1, seq)
            + _encode(5, 1)
            + _encode(8, _with_varint(schedule, 1, timestamp))
            + _encode(9, _with_varint(state, 1, timestamp))
        )
        self._unacked[serial] = seq
        try:
            writer.write(_frame(body))
            await writer.drain()
        except OSError:
            self._unacked.pop(serial, None)
            raise

    # --- framing ------------------------------------------------------------
    @staticmethod
    async def _read_frame(
        reader: asyncio.StreamReader, idle_timeout: float | None = None
    ) -> bytes:
        """Read one 0x08<len><body> frame; TimeoutError if the link goes quiet."""
        async with asyncio.timeout(idle_timeout):
            hdr = await reader.readexactly(1)
            if hdr[0] != 0x08:
                msg = f"unexpected frame start {hdr[0]:#x}"
                raise ValueError(msg)
            length = shift = 0
            while True:
                b = (await reader.readexactly(1))[0]
                length |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
                if shift > 28:
                    msg = "frame length varint too long"
                    raise ValueError(msg)
            if length > MAX_FRAME:
                msg = f"frame of {length} bytes exceeds {MAX_FRAME}"
                raise ValueError(msg)
            return await reader.readexactly(length)

    # --- commands -----------------------------------------------------------
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _build_set(
        self, serial: str, mode: int, setpoint_x200: int | None
    ) -> bytes | None:
        """Build a set-command body from the thermostat's own last state.

        The command's state is a copy of that state with a fresh timestamp and
        the new mode. A hold's setpoint goes into that hold's own sub-message
        (9.4 temporary, 9.5 permanent); everything else, including the other
        hold's setpoint and the temporary hold's end time, goes back exactly as
        the thermostat sent it. Without a setpoint (back to the schedule) only
        the mode changes.
        """
        f9raw = self._state_raw.get(serial)
        if f9raw is None:
            return None  # no template captured yet; flushed after next upload
        st = parse(f9raw)
        st[1] = [_server_time()]
        st[2] = [mode]
        hold = _HOLD_FIELD.get(mode)
        if hold is not None and setpoint_x200 is not None:
            current = st.get(hold, [b""])[0]
            sub = current if isinstance(current, bytes) else b""
            st[hold] = [_with_varint(sub, 1, setpoint_x200)]
        body9 = b"".join(
            _encode(number, value) for number in sorted(st) for value in st[number]
        )
        body = _tag(1, 0) + wvarint(self._next_seq()) + _tag(5, 0) + wvarint(1)
        if f8 := self._sched.get(serial):
            body += _encode(8, f8)
        return body + _encode(9, body9)

    async def queue_set(
        self, serial: str, mode: int, setpoint_x200: int | None
    ) -> None:
        """Ask the device to hold setpoint_x200 (Celsius x200) in mode.

        If the thermostat is not connected yet, or has not uploaded a state frame
        to use as a template, the change is kept and sent as soon as it can be.
        """
        self._desired[serial] = (mode, setpoint_x200)
        _LOGGER.debug(
            "WG4 change queued for %s: mode %s (%s), setpoint %s",
            serial,
            mode,
            _MODE_NAMES.get(mode, "unknown"),
            "unchanged" if setpoint_x200 is None else _temp(setpoint_x200),
        )
        await self._flush(serial)

    async def _flush(self, serial: str) -> None:
        if serial not in self._desired:
            return
        writer = self._writers.get(serial)
        if writer is None:
            _LOGGER.debug(
                "WG4 thermostat %s isn't connected; the change will be sent "
                "when it connects",
                serial,
            )
            return
        mode, setpoint = self._desired[serial]
        body = self._build_set(serial, mode, setpoint)
        if body is None:
            _LOGGER.debug(
                "WG4 has no state from %s to build the command from yet; the "
                "change will be sent after its next state upload",
                serial,
            )
            return
        top = parse(body)
        self._log_frame("command", serial, top)
        self._unacked[serial] = top[1][0]
        try:
            writer.write(_frame(body))
            await writer.drain()
        except OSError as err:
            self._unacked.pop(serial, None)
            _LOGGER.debug("WG4 set-command to %s failed: %s", serial, err)
            return
        self._desired.pop(serial, None)
        _LOGGER.debug(
            "WG4 sent set-command seq %s to %s (mode %s, setpoint %s)",
            top[1][0],
            serial,
            mode,
            "unchanged" if setpoint is None else _temp(setpoint),
        )

    def _note_ack(self, serial: str | None, top: Fields) -> None:
        """Log when the thermostat acknowledges the command we last sent it."""
        if (
            serial
            and top.get(3) == [1]
            and 2 not in top
            and top.get(1, [None])[0] == self._unacked.get(serial)
        ):
            del self._unacked[serial]
            _LOGGER.debug(
                "WG4 thermostat %s acknowledged set-command seq %s (3=%s)",
                serial,
                top[1][0],
                top[3][0],
            )

    def _capture(self, serial: str, top: Fields) -> None:
        if 8 in top:
            self._sched[serial] = top[8][0]
        if 9 in top:
            self._state_raw[serial] = top[9][0]

    # --- connection handling ------------------------------------------------
    def _logged_in(self, serial: str | None, writer: asyncio.StreamWriter) -> None:
        if not serial:
            return
        old = self._writers.get(serial)
        self._writers[serial] = writer
        self._state_raw.pop(serial, None)
        self._sched.pop(serial, None)
        self._unacked.pop(serial, None)
        if old is not None and old is not writer:
            old.close()  # the device reconnected; drop the stale link
        _LOGGER.info(
            "WG4 thermostat %s connected to the local gateway",
            serial,
        )
        self.on_state(serial, {"Online": True})

    def _dispatch(self, serial: str | None, body: bytes, top: Fields) -> None:
        """Feed a frame that describes the thermostat to Home Assistant.

        State arrives in the full upload after login (field 2 = 4), and in
        shorter frames when someone changes the thermostat at the wall.
        """
        if not serial:
            return
        if 8 in top or 9 in top:
            self._capture(serial, top)
        if 8 in top:
            self.on_state(serial, {"LocalScheduleRaw": top[8][0]})
        if 7 in top or 9 in top:
            if fields := _decode_state(body):
                self.on_state(serial, fields)
        elif 15 in top:
            self.on_state(serial, _decode_telemetry(top[15][0]))

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("WG4 device connection from %s", peer)
        self._conns.add(writer)
        conn: dict[str, str | None] = {"serial": None}
        try:
            await self._serve_local(reader, writer, conn)
        except asyncio.IncompleteReadError, ConnectionError, ssl.SSLError:
            pass
        except TimeoutError:
            _LOGGER.debug("WG4 device %s went quiet; closing", conn["serial"] or peer)
        except ValueError as err:
            _LOGGER.debug("WG4 dropped a malformed connection from %s: %s", peer, err)
        except Exception:  # pylint: disable=broad-exception-caught
            # Isolate a malformed device connection from the HA event loop.
            _LOGGER.exception("WG4 gateway connection error")
        finally:
            self._conns.discard(writer)
            serial = conn["serial"]
            # Only report offline if a newer connection hasn't replaced this one.
            if serial and self._writers.get(serial) is writer:
                del self._writers[serial]
                _LOGGER.info(
                    "WG4 thermostat %s disconnected from the local gateway", serial
                )
                self.on_state(serial, {"Online": False})
            with suppress(OSError):
                writer.close()

    async def _serve_local(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        conn: dict[str, str | None],
    ) -> None:
        """Answer the device from its captured configuration and fresh state."""
        while True:
            body = await self._read_frame(reader, DEVICE_IDLE_TIMEOUT)
            top = parse(body)
            self._log_frame("device", conn["serial"], top)
            seq = top.get(1, [0])[0]
            kind = top.get(2, [None])[0]
            if 6 in top:  # login
                conn["serial"] = _login_serial(top)
                if (
                    self._allowed_serials is not None
                    and conn["serial"] not in self._allowed_serials
                ):
                    msg = "Thermostat is not registered for this gateway"
                    raise ValueError(msg)
                writer.write(_login_ack(seq))
                await writer.drain()
                self._logged_in(conn["serial"], writer)
                continue
            self._dispatch(conn["serial"], body, top)
            if kind == 6:  # schedule upload
                writer.write(_ack(seq))
                writer.write(self._support_frame)
            elif kind == 4:  # state upload
                writer.write(_ack(seq))
                writer.write(self._configuration_frame)
            elif 3 in top and 2 not in top:  # the device acking us
                self._note_ack(conn["serial"], top)
                continue
            elif seq:  # telemetry and anything else that wants an ack
                writer.write(_ack(seq))
            else:
                continue
            await writer.drain()
            if 9 in top and conn["serial"]:
                await self._flush(conn["serial"])

    @staticmethod
    def _log_frame(source: str, serial: str | None, top: Fields) -> None:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "WG4 %s frame (%s): %s",
                source,
                serial or "before login",
                "login" if 6 in top else _describe(top),
            )
