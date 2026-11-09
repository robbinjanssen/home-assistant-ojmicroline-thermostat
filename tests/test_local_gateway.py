"""Protocol unit tests for the local device gateway.

These exercise the wire-format helpers directly and need no Home Assistant
fixtures. Setpoints on the device are Celsius x200, while the coordinator uses
Celsius x100; getting that scale wrong writes half the intended temperature, so
it is pinned here. So is which field each hold keeps its setpoint in: a
permanent hold written to the temporary hold's field leaves the thermostat at
its old permanent setpoint.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ojmicroline_thermostat import local_gateway as g
from custom_components.ojmicroline_thermostat.local_cert import _generate

from .test_local_schedule import schedule_wire

# Protocol regression tests deliberately inspect the wire implementation.
# pylint: disable=protected-access

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.core import HomeAssistant

# A login frame shaped like the thermostat's (account email, serial and a number
# we don't use), with a placeholder email.
_ACCOUNT = (
    g._tag(1, 2)
    + g.wvarint(16)
    + b"user@example.com"
    + g._tag(2, 2)
    + g.wvarint(7)
    + b"1254414"
    + g._tag(3, 0)
    + g.wvarint(10207)
)
LOGIN = g._frame(
    g._tag(1, 0)
    + g.wvarint(29)
    + g._tag(5, 0)
    + g.wvarint(1)
    + g._tag(6, 2)
    + g.wvarint(len(_ACCOUNT))
    + _ACCOUNT
)


def _strip(frame: bytes) -> bytes:
    """Strip."""
    assert frame[0] == 0x08
    length, j = g.uvarint(frame, 1)
    body = frame[j:]
    assert len(body) == length
    return body


def _wrap(field: int, body: bytes) -> bytes:
    """Wrap."""
    return g._tag(field, 2) + g.wvarint(len(body)) + body


def _make_f9(mode: int, *, temporary: int = 3332, permanent: int = 4444) -> bytes:
    """Build a state shaped like the thermostat's, setpoints in Celsius x200."""
    return (
        g._tag(1, 0)
        + g.wvarint(1000)
        + g._tag(2, 0)
        + g.wvarint(mode)
        + _wrap(4, g._tag(1, 0) + g.wvarint(temporary))
        + _wrap(5, g._tag(1, 0) + g.wvarint(permanent))
        + g._tag(6, 0)
        + g.wvarint(0)
    )


# The state from a real upload while the thermostat held 58 F permanently: mode 3,
# temporary setpoint 9.4.1 = 2666 (13.33 C), permanent setpoint 9.5.1 = 2888
# (14.44 C, 58 F). Its device info reported 7.9 = 2888, the permanent one.
PERMANENT_F9 = bytes.fromhex(
    "08c5e4f4920310031a020800220908ea1410809cf692032a0308c8163000"
)


def test_varint_roundtrip() -> None:
    """Test varint roundtrip."""
    for n in (0, 1, 127, 128, 2666, 4444, 946684800):
        encoded = g.wvarint(n)
        assert g.uvarint(encoded, 0) == (n, len(encoded))


def test_login_serial() -> None:
    """Test login serial."""
    assert g._login_serial(g.parse(_strip(LOGIN))) == "1254414"


def test_decode_state_uses_x200_scale() -> None:
    # 22.22 C held permanently -> device field 4444 (x200) -> 2222 (x100).
    """Test decode state uses x200 scale."""
    body = _wrap(7, _wrap(2, b"Kitchen Floor")) + _wrap(9, _make_f9(3))
    fields = g._decode_state(body)
    assert fields == {
        "RegulationMode": 3,
        "ComfortTemperature": 1666,
        "ManualTemperature": 2222,
        "SetPointTemp": 2222,
        "Room": "Kitchen Floor",
    }


def test_decode_state_reads_each_holds_own_setpoint() -> None:
    # A real permanent hold at 58 F: the active setpoint is 9.5.1, not 9.4.1.
    """Test decode state reads each holds own setpoint."""
    fields = g._decode_state(_wrap(9, PERMANENT_F9))
    assert fields == {
        "RegulationMode": 3,
        "ComfortTemperature": 1333,
        "ManualTemperature": 1444,
        "SetPointTemp": 1444,
    }
    # A temporary hold uses 9.4.1.
    assert g._decode_state(_wrap(9, _make_f9(2)))["SetPointTemp"] == 1666
    # The schedule's setpoint isn't in the state; it comes from device info 7.9.
    schedule = g._decode_state(_wrap(9, _make_f9(1)))
    assert "SetPointTemp" not in schedule
    info = _wrap(7, g._tag(9, 0) + g.wvarint(4000))
    assert g._decode_state(_wrap(9, _make_f9(1)) + info)["SetPointTemp"] == 2000


def test_build_set_roundtrip() -> None:
    """Test build set roundtrip."""
    gw = g.LocalGateway(
        "cert",
        "key",
        allowed_serials={"1254414"},
        configuration_frame=CONFIG,
        support_frame=SUPPORT,
        on_state=lambda *_a: None,
    )
    gw._state_raw["1254414"] = _make_f9(3, temporary=2666, permanent=2888)
    top = g.parse(_build_set(gw, "1254414", 3, 5000))
    assert top[5][0] == 1
    f9 = g.parse(top[9][0])
    assert f9[2][0] == 3  # permanent hold
    assert g.parse(f9[5][0])[1][0] == 5000  # new permanent setpoint, x200
    assert g.parse(f9[4][0])[1][0] == 2666  # temporary setpoint untouched


def test_build_set_without_template_returns_none() -> None:
    """Test build set without template returns none."""
    gw = g.LocalGateway(
        "cert",
        "key",
        allowed_serials={"1254414"},
        configuration_frame=CONFIG,
        support_frame=SUPPORT,
        on_state=lambda *_a: None,
    )
    assert gw._build_set("unknown", 3, 5000) is None


def test_decode_telemetry_heating_flag() -> None:
    # Real telemetry frames captured across a heat/stop: field 1 is the current
    # temperature (x100) and field 2 is the live heating flag (1 on, 0 idle).
    """Test decode telemetry heating flag."""
    idle = bytes.fromhex("08f10f1000200028003000388c04")
    heating = bytes.fromhex("08ee0f1001200028003000389904")
    assert g._decode_telemetry(idle) == {"Temperature": 2033, "Heating": False}
    assert g._decode_telemetry(heating) == {"Temperature": 2030, "Heating": True}


# --- connection handling ----------------------------------------------------
CONFIG = g._frame(g._encode(10, g._encode(1, 1)))
SUPPORT = g._frame(g._encode(18, g._encode(1, b"Example support")))
SERIAL = "1254414"
# Real frames from a heat/stop capture: telemetry, a setpoint change made at the
# thermostat (field 9 only, no field 2), and its device-info follow-up.
TELEMETRY = bytes.fromhex("08930328017a0e08f10f1000200028003000388c04")
WALL_STATE = bytes.fromhex(
    "08960328014a1e08cedbf6920310021a020800220908ec2110e0c4f792032a0308c8163000"
)
WALL_INFO = bytes.fromhex(
    "08970328013a1708d0dbf6920330e80738c03e48ec215001581968017064"
)
DEVICE_ACK = g._tag(1, 0) + g.wvarint(0) + g._tag(3, 0) + g.wvarint(1)
UNKNOWN = g._tag(1, 0) + g.wvarint(55) + g._tag(20, 0) + g.wvarint(1)
NO_SEQ = g._tag(20, 0) + g.wvarint(1)


def _state_upload(seq: int = 31, setpoint_x200: int = 4444) -> bytes:
    """State upload."""
    return (
        g._tag(1, 0)
        + g.wvarint(seq)
        + g._tag(2, 0)
        + g.wvarint(4)
        + g._tag(5, 0)
        + g.wvarint(1)
        + _wrap(7, _wrap(2, b"Kitchen Floor"))
        + _wrap(8, b"\x08\x01")
        + _wrap(9, _make_f9(3, permanent=setpoint_x200))
    )


def _schedule_upload(seq: int = 30) -> bytes:
    """Schedule upload."""
    return g._tag(1, 0) + g.wvarint(seq) + g._tag(2, 0) + g.wvarint(6)


class FakeWriter(asyncio.StreamWriter):
    # pylint: disable=super-init-not-called,arguments-differ
    """Fakewriter."""

    def __init__(self) -> None:
        """Init  ."""
        self.data = bytearray()
        self.closed = False

    def __del__(self, _warnings: Any = None, /) -> None:
        """Skip real transport cleanup for this fake."""

    def write(self, data: Any) -> None:
        """Write."""
        self.data += data

    async def drain(self) -> None:
        """Drain."""
        return

    def close(self) -> None:
        """Close."""
        self.closed = True

    def get_extra_info(self, name: str, default: Any = None) -> Any:  # noqa: ARG002
        # Match StreamWriter while keeping the fake independent of transports.
        """Get extra info."""
        return ("192.168.1.171", 50000)

    def frames(self) -> list[g.Fields]:
        """Frames."""
        out, i = [], 0
        while i < len(self.data):
            length, j = g.uvarint(bytes(self.data), i + 1)
            out.append(g.parse(bytes(self.data[j : j + length])))
            i = j + length
        return out


def _reader(*bodies: bytes, eof: bool = True) -> asyncio.StreamReader:
    """Reader."""
    reader = asyncio.StreamReader()
    for body in bodies:
        reader.feed_data(g._frame(body))
    if eof:
        reader.feed_eof()
    return reader


def _gateway() -> tuple[g.LocalGateway, list[tuple[str, dict[str, Any]]]]:
    """Gateway."""
    events: list[tuple[str, dict[str, Any]]] = []
    gw = g.LocalGateway(
        "cert",
        "key",
        allowed_serials={SERIAL},
        configuration_frame=CONFIG,
        support_frame=SUPPORT,
        on_state=lambda s, f: events.append((s, f)),
    )
    return gw, events


async def test_local_session_answers_and_decodes() -> None:
    """Test local session answers and decodes."""
    gw, events = _gateway()
    writer = FakeWriter()
    await gw._handle(
        _reader(
            _strip(LOGIN),
            _schedule_upload(),
            _state_upload(),
            TELEMETRY,
            WALL_STATE,
            WALL_INFO,
            DEVICE_ACK,
            UNKNOWN,
            NO_SEQ,
        ),
        writer,
    )
    assert (SERIAL, {"LocalScheduleRaw": b"\x08\x01"}) in events
    events = [
        (serial, fields)
        for serial, fields in events
        if "LocalScheduleRaw" not in fields
    ]
    replies = writer.frames()
    assert 12 in replies[0]
    assert replies[0][1] == [29]
    assert replies[1] == {1: [30], 3: [1]}  # schedule ack, then customer-service info
    assert 18 in replies[2]
    assert replies[3] == {1: [31], 3: [1]}  # state ack, then config
    assert 10 in replies[4]
    acked = [r[1][0] for r in replies[5:]]
    assert acked == [403, 406, 407, 55]  # telemetry, wall change, info, unknown

    assert events[0] == (SERIAL, {"Online": True})
    assert events[1] == (
        SERIAL,
        {
            "RegulationMode": 3,
            "ComfortTemperature": 1666,
            "ManualTemperature": 2222,
            "SetPointTemp": 2222,
            "Room": "Kitchen Floor",
        },
    )
    assert events[2] == (SERIAL, {"Temperature": 2033, "Heating": False})
    # A change made at the wall (a temporary hold at 71 F) reaches Home Assistant,
    # along with the permanent setpoint it keeps in reserve (58 F).
    assert events[3] == (
        SERIAL,
        {
            "RegulationMode": 2,
            "ComfortTemperature": 2166,
            "ManualTemperature": 1444,
            "SetPointTemp": 2166,
        },
    )
    # Its device-info follow-up confirms the setpoint the thermostat aims for.
    assert events[4] == (SERIAL, {"SetPointTemp": 2166})
    assert events[-1] == (SERIAL, {"Online": False})
    assert len(events) == 6
    assert writer.closed
    assert gw.connected_serials == set()


async def test_set_waits_for_connection_and_template(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test set waits for connection and template."""
    caplog.set_level(logging.DEBUG)
    gw, _ = _gateway()
    await gw.queue_set(SERIAL, 3, 5000)  # not connected yet: kept
    assert f"WG4 thermostat {SERIAL} isn't connected" in caplog.text
    writer = FakeWriter()
    command_ack = g._tag(1, 0) + g.wvarint(101) + g._tag(3, 0) + g.wvarint(1)
    await gw._handle(_reader(_strip(LOGIN), _state_upload(), command_ack), writer)
    command = writer.frames()[-1]
    assert command[1] == [101]
    assert command[5] == [1]
    assert 8 in command
    f9 = g.parse(command[9][0])
    assert f9[2] == [3]
    assert g.parse(f9[5][0])[1] == [5000]
    assert SERIAL not in gw._desired
    assert (
        f"WG4 thermostat {SERIAL} acknowledged set-command seq 101 (3=1)" in caplog.text
    )
    assert SERIAL not in gw._unacked

    # Once sent it isn't repeated, and a set with no connection does nothing.
    await gw._flush(SERIAL)
    await gw.queue_set("other", 1, None)
    assert "other" in gw._desired


async def test_set_write_failure_keeps_it_pending() -> None:
    """Test set write failure keeps it pending."""
    gw, _ = _gateway()
    gw._state_raw[SERIAL] = _make_f9(3)
    writer = FakeWriter()
    gw._writers[SERIAL] = writer
    with patch.object(writer, "drain", AsyncMock(side_effect=ConnectionResetError)):
        await gw.queue_set(SERIAL, 3, 5000)
    assert SERIAL in gw._desired


async def test_reconnect_replaces_old_link() -> None:
    """Test reconnect replaces old link."""
    gw, events = _gateway()
    first_reader, first = _reader(_strip(LOGIN), eof=False), FakeWriter()
    first_task = asyncio.create_task(gw._handle(first_reader, first))
    await asyncio.sleep(0)
    second_reader, second = _reader(_strip(LOGIN), eof=False), FakeWriter()
    second_task = asyncio.create_task(gw._handle(second_reader, second))
    await asyncio.sleep(0)
    assert first.closed
    assert gw._writers[SERIAL] is second

    # The stale link ending must not mark the thermostat offline.
    first_reader.feed_eof()
    await first_task
    assert events[-1] == (SERIAL, {"Online": True})
    second_reader.feed_eof()
    await second_task
    assert events[-1] == (SERIAL, {"Online": False})


async def test_quiet_link_is_closed() -> None:
    """Test quiet link is closed."""
    gw, events = _gateway()
    with patch.object(g, "DEVICE_IDLE_TIMEOUT", 0.01):
        await gw._handle(_reader(_strip(LOGIN), eof=False), FakeWriter())
    assert events[-1] == (SERIAL, {"Online": False})


@pytest.mark.parametrize(
    "raw",
    [
        b"\x07\x00",  # wrong frame start
        b"\x08" + g.wvarint(g.MAX_FRAME + 1),  # absurd length
        b"\x08" + b"\xff" * 6,  # runaway length varint
    ],
)
async def test_malformed_input_is_dropped(raw: bytes) -> None:
    """Test malformed input is dropped."""
    gw, events = _gateway()
    reader = asyncio.StreamReader()
    reader.feed_data(raw)
    reader.feed_eof()
    writer = FakeWriter()
    await gw._handle(reader, writer)
    assert writer.closed
    assert not events


async def test_unexpected_error_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Test unexpected error is logged."""

    def boom(_serial: str, fields: dict[str, Any]) -> None:
        """Boom."""
        if "Online" not in fields:
            msg = "bad"
            raise RuntimeError(msg)

    gw = g.LocalGateway(
        "cert",
        "key",
        allowed_serials={"1254414"},
        configuration_frame=CONFIG,
        support_frame=SUPPORT,
        on_state=boom,
    )
    await gw._handle(_reader(_strip(LOGIN), TELEMETRY), FakeWriter())
    assert "WG4 gateway connection error" in caplog.text


CLOUD_LOGIN_ACK = bytes.fromhex("081d18012001620608c5e4f49203")
CLOUD_ROOM = (
    g._tag(1, 0)
    + g.wvarint(2)
    + g._tag(5, 0)
    + g.wvarint(1)
    + _wrap(7, _wrap(2, b"Bathroom"))
)


async def test_start_and_stop(hass: HomeAssistant, tmp_path: Path) -> None:
    """Test start and stop."""
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    _generate(cert, key)
    server = MagicMock()
    server.wait_closed = AsyncMock(side_effect=OSError)
    gw = g.LocalGateway(
        str(cert),
        str(key),
        allowed_serials={SERIAL},
        configuration_frame=CONFIG,
        support_frame=SUPPORT,
        on_state=lambda *_a: None,
        port=0,
    )
    with patch.object(asyncio, "start_server", AsyncMock(return_value=server)) as start:
        await gw.start(hass)
    assert start.call_args.kwargs["ssl"] is gw._server_ctx
    link = FakeWriter()
    gw._conns.add(link)
    gw._writers[SERIAL] = link
    await gw.stop()
    assert link.closed
    assert server.close.called
    assert gw.connected_serials == set()
    await gw.stop()  # stopping twice is harmless


def test_decode_telemetry_without_heating_field() -> None:
    """Test decode telemetry without heating field."""
    assert g._decode_telemetry(g._tag(1, 0) + g.wvarint(2100)) == {"Temperature": 2100}


def test_login_without_serial() -> None:
    """Test login without serial."""
    assert g._login_serial({1: [1]}) is None


def test_build_set_permanent_hold_writes_its_own_field() -> None:
    # The bug this pins: from a real temporary hold at 71 F with 58 F stored as
    # the permanent setpoint, a permanent hold at 22.5 C must replace the 58 F,
    # and the temporary hold's setpoint and end time stay as they were.
    """Test build set permanent hold writes its own field."""
    gw, _ = _gateway()
    top = g.parse(WALL_STATE)
    gw._capture(SERIAL, top)
    f9 = g.parse(g.parse(_build_set(gw, SERIAL, 3, 4500))[9][0])
    original = g.parse(top[9][0])
    assert f9[2] == [3]
    assert g.parse(f9[5][0]) == {1: [4500]}
    assert (f9[3], f9[4], f9[6]) == (original[3], original[4], original[6])


def test_build_set_temporary_hold_keeps_end_time() -> None:
    """Test build set temporary hold keeps end time."""
    gw, _ = _gateway()
    top = g.parse(WALL_STATE)
    gw._capture(SERIAL, top)
    f9 = g.parse(g.parse(_build_set(gw, SERIAL, 2, 4000))[9][0])
    original = g.parse(top[9][0])
    assert f9[2] == [2]
    f4 = g.parse(f9[4][0])
    assert f4[1] == [4000]
    assert f4[2] == g.parse(original[4][0])[2]
    assert (f9[3], f9[5], f9[6]) == (original[3], original[5], original[6])


def test_build_set_schedule_changes_only_the_mode() -> None:
    """Test build set schedule changes only the mode."""
    gw, _ = _gateway()
    gw._state_raw[SERIAL] = PERMANENT_F9
    f9 = g.parse(g.parse(_build_set(gw, SERIAL, 1, None))[9][0])
    original = g.parse(PERMANENT_F9)
    assert f9[2] == [1]
    assert {k: v for k, v in f9.items() if k not in (1, 2)} == {
        k: v for k, v in original.items() if k not in (1, 2)
    }


def test_build_set_copies_the_state_byte_for_byte() -> None:
    # Re-encoding must give back the thermostat's own bytes: same mode, same
    # setpoint and same timestamp produce the identical state.
    """Test build set copies the state byte for byte."""
    gw, _ = _gateway()
    gw._state_raw[SERIAL] = PERMANENT_F9
    original = g.parse(PERMANENT_F9)
    with patch.object(g, "_server_time", return_value=original[1][0]):
        body = gw._build_set(SERIAL, 3, 2888)
    assert g.parse(body or b"")[9][0] == PERMANENT_F9


def test_build_set_adds_a_missing_hold() -> None:
    """Test build set adds a missing hold."""
    gw, _ = _gateway()
    gw._state_raw[SERIAL] = g._tag(1, 0) + g.wvarint(1000) + g._tag(2, 0) + g.wvarint(1)
    f9 = g.parse(g.parse(_build_set(gw, SERIAL, 3, 4500))[9][0])
    assert f9[2] == [3]
    assert g.parse(f9[5][0]) == {1: [4500]}


def test_describe_shows_holds_and_unknown_fields() -> None:
    """Test describe shows holds and unknown fields."""
    assert g._describe(g.parse(WALL_STATE)) == (
        "seq=406 fields=1,5,9 mode=2 (temporary hold) temporary=21.66C/71.0F "
        "until=2026-10-11 06:00:00Z permanent=14.44C/58.0F 9.3={1: 0} 9.6=0"
    )
    assert g._describe(g.parse(WALL_INFO)) == "seq=407 fields=1,5,7 target=21.66C/71.0F"
    assert g._describe(g.parse(TELEMETRY)) == (
        "seq=403 fields=1,5,15 floor=20.33C/68.6F heating=0"
    )
    odd = (
        g._tag(2, 0)
        + g.wvarint(9)
        + _wrap(3, g._tag(1, 0) + g.wvarint(0) + _wrap(2, b"\x01\x02"))
    )
    assert (
        g._describe({9: [odd]})
        == "seq=None fields=9 mode=9 (unknown) 9.3={1: 0, 2: 0102}"
    )


async def test_set_without_template_waits_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test set without template waits and says so."""
    caplog.set_level(logging.DEBUG)
    gw, _ = _gateway()
    gw._writers[SERIAL] = FakeWriter()
    await gw.queue_set(SERIAL, 1, None)
    assert (
        f"WG4 change queued for {SERIAL}: mode 1 (schedule), setpoint unchanged"
        in caplog.text
    )
    assert f"WG4 has no state from {SERIAL}" in caplog.text
    assert SERIAL in gw._desired


def test_parse_fixed_width_and_unknown_wire_types() -> None:
    """Test parse fixed width and unknown wire types."""
    body = g._tag(1, 5) + b"\x01\x02\x03\x04" + g._tag(2, 1) + b"\x00" * 8
    assert g.parse(body) == {1: [b"\x01\x02\x03\x04"], 2: [b"\x00" * 8]}


async def test_frames_before_login_are_ignored() -> None:
    """Test frames before login are ignored."""
    gw, events = _gateway()
    writer = FakeWriter()
    await gw._handle(
        _reader(TELEMETRY, g._tag(1, 0) + g.wvarint(9) + _wrap(6, b"")), writer
    )
    assert not events  # no serial yet, and a login without one isn't trusted
    assert writer.frames()[0] == {1: [403], 3: [1]}


async def test_unregistered_device_gets_no_login_ack() -> None:
    """Test unregistered device gets no login ack."""
    gw, events = _gateway()
    gw._allowed_serials = {"other"}
    writer = FakeWriter()
    await gw._handle(_reader(_strip(LOGIN)), writer)
    assert not writer.data
    assert writer.closed
    assert not events


@pytest.mark.parametrize("raw", [b"", b"\x80", b"\xff" * 11])
def test_invalid_varint_is_rejected(raw: bytes) -> None:
    """Test invalid varint is rejected."""
    with pytest.raises(ValueError, match="varint"):
        g.uvarint(raw, 0)


def test_negative_varint_is_rejected() -> None:
    """Test negative varint is rejected."""
    with pytest.raises(ValueError, match="negative"):
        g.wvarint(-1)


def _build_set(gw: g.LocalGateway, serial: str, mode: int, temp: int | None) -> bytes:
    """Require a command for a gateway with a known template."""
    body = gw._build_set(serial, mode, temp)
    assert body is not None
    return body


@pytest.mark.parametrize("body", [b"\x00", b"\x1b", b"\x0a\x05x", b"\x0d\x00"])
def test_truncated_fields_are_rejected(body: bytes) -> None:
    """Reject malformed bodies rather than accepting a partial private profile."""
    with pytest.raises(ValueError, match="protobuf"):
        g.parse(body)


async def test_schedule_write_preserves_mode_and_requires_readback() -> None:
    """Send a fresh schedule without changing mode/holds or trusting an ACK alone."""
    gw, events = _gateway()
    writer = FakeWriter()
    gw._writers[SERIAL] = writer
    gw._state_raw[SERIAL] = PERMANENT_F9
    gw._sched[SERIAL] = b"previous"
    raw = schedule_wire()
    await gw.send_schedule(SERIAL, raw)
    command = writer.frames()[0]
    scheduled = g.parse(command[8][0])
    assert scheduled[2] == g.parse(raw)[2]
    assert scheduled[1] == g.parse(command[9][0])[1]
    state = g.parse(command[9][0])
    original = g.parse(PERMANENT_F9)
    assert {k: v for k, v in state.items() if k != 1} == {
        k: v for k, v in original.items() if k != 1
    }
    assert gw.schedule_template(SERIAL) == b"previous"
    assert gw.is_waiting_for_ack(SERIAL)
    gw._note_ack(SERIAL, {1: command[1], 3: [0]})
    assert gw.is_waiting_for_ack(SERIAL)
    gw._note_ack(SERIAL, {1: command[1], 3: [1]})
    assert not gw.is_waiting_for_ack(SERIAL)
    gw._dispatch(SERIAL, g._encode(8, raw), {8: [raw]})
    assert gw.schedule_template(SERIAL) == raw
    assert events == [(SERIAL, {"LocalScheduleRaw": raw})]
    gw.request_schedule_readback(SERIAL)
    assert writer.closed


async def test_schedule_send_rejects_uninitialized_device() -> None:
    """Do not queue a schedule to be applied on a later connection."""
    gw, _ = _gateway()
    with pytest.raises(ValueError, match="connected thermostat"):
        await gw.send_schedule(SERIAL, b"schedule")


async def test_schedule_send_failure_cleans_up_ack() -> None:
    """Avoid claiming a failed write is awaiting acknowledgement."""
    gw, _ = _gateway()
    writer = FakeWriter()
    gw._writers[SERIAL] = writer
    gw._state_raw[SERIAL] = PERMANENT_F9
    gw._sched[SERIAL] = b"previous"
    with (
        patch.object(writer, "drain", AsyncMock(side_effect=ConnectionResetError)),
        pytest.raises(ConnectionResetError),
    ):
        await gw.send_schedule(SERIAL, schedule_wire())
    assert not gw.is_waiting_for_ack(SERIAL)
    assert gw.schedule_template(SERIAL) == b"previous"


def test_timestamp_replacement_preserves_unknown_wire_fields() -> None:
    """Keep unknown fixed-width fields unchanged when updating command versions."""
    unknown = g._tag(12, 5) + b"abcd"
    original = g._encode(1, 1234) + unknown
    assert g._with_varint(original, 1, 5678) == g._encode(1, 5678) + unknown
