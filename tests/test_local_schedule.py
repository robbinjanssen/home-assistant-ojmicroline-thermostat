"""Synthetic WG4 schedules: scaling, weekday order, and lossless edits."""

from datetime import time
from typing import Any

import pytest

from custom_components.ojmicroline_thermostat import local_gateway as g
from custom_components.ojmicroline_thermostat.local_schedule import (
    decode_schedule,
    encode_schedule,
    set_local_days,
)
from custom_components.ojmicroline_thermostat.schedule import ScheduleError

# Wire tests intentionally exercise the protocol encoding helpers.
# pylint: disable=protected-access


def schedule_wire() -> bytes:
    """Build seven distinct days, with unknown fields at every nesting level."""
    days = []
    for day in range(1, 8):
        events = []
        for slot, hour in enumerate((6, 9, 12, 14, 18, 22)):
            clock = g._encode(1, hour) + g._encode(2, 0) + g._encode(3, 0)
            clock += g._tag(10, 5) + b"abcd"  # Preserve unknown fixed-width fields.
            event = (
                g._encode(1, clock)
                + g._encode(2, 1700 + day * 10 + slot)
                + g._encode(3, int(slot in (0, 1, 4, 5)))
                + g._encode(11, b"unknown event")
            )
            events.append(g._encode(2, event))
        days.append(g._encode(1, g._encode(1, day) + b"".join(events)))
    return g._encode(1, 1234) + g._encode(2, b"".join(days)) + g._encode(9, 77)


def test_weekdays_and_schedule_temperature_scale() -> None:
    """Use Monday-first day IDs and x100 temperatures, not hold x200 scaling."""
    schedule = decode_schedule(schedule_wire())
    assert len(schedule["Days"]) == 7
    assert schedule["Days"][0]["Events"][0]["Temperature"] == 1710
    assert schedule["Days"][6]["Events"][0]["Temperature"] == 1770
    assert not schedule["Days"][0]["Events"][2]["Active"]


def test_unchanged_schedule_is_byte_identical() -> None:
    """Keep unknown fields, inactive slots, and timestamps byte for byte."""
    raw = schedule_wire()
    assert encode_schedule(raw, decode_schedule(raw)) == raw


def test_one_day_edit_preserves_other_days_and_inactive_slots() -> None:
    """Change one setpoint and preserve every unrelated wire byte."""
    raw = schedule_wire()
    original = decode_schedule(raw)
    events = original["Days"][6]["Events"]
    requested = [
        (time.fromisoformat(e["Clock"]), e["Temperature"] / 100)
        for e in events
        if e["Active"]
    ]
    requested[-1] = (requested[-1][0], 20.5)
    updated = set_local_days(original, ["sunday"], requested, 500, 4000)
    result = encode_schedule(raw, updated)
    decoded = decode_schedule(result)
    assert decoded["Days"][:6] == original["Days"][:6]
    assert decoded["Days"][6]["Events"][2:4] == events[2:4]
    assert decoded["Days"][6]["Events"][5]["Temperature"] == 2050
    assert encode_schedule(result, original) == raw
    before = g.parse(g.parse(raw)[2][0])[1]
    after = g.parse(g.parse(result)[2][0])[1]
    assert before[:6] == after[:6]


def test_multi_day_add_remove_and_first_slot() -> None:
    """Allow six active events and keep the mandatory first slot active."""
    original = decode_schedule(schedule_wire())
    updated = set_local_days(
        original,
        ["monday", "tuesday"],
        [(time(h), 21) for h in (6, 9, 12, 14, 18, 22)],
        500,
        4000,
    )
    assert all(e["Active"] for e in updated["Days"][0]["Events"])
    removed = set_local_days(updated, ["monday"], [(time(6), 21)], 500, 4000)
    assert [e["Active"] for e in removed["Days"][0]["Events"]] == [
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    assert updated["Days"][2:] == original["Days"][2:]


@pytest.mark.parametrize(
    ("days", "events"),
    [
        ([], [(time(6), 21)]),
        (["monday"], []),
        (["monday"], [(time(6), float("nan"))]),
        (["monday"], [(time(6), 41)]),
        (["monday"], [(time(6, 1), 21)]),
        (["monday"], [(time(6, 0, 1), 21)]),
        (["monday"], [(time(6), 21), (time(6), 20)]),
        (["monday"], [(time(23), 21), (time(1), 20)]),
    ],
)
def test_invalid_edits_rejected(
    days: list[str], events: list[tuple[time, float]]
) -> None:
    """Reject unsupported clocks, nonfinite temperatures, and missing selections."""
    with pytest.raises(ScheduleError):
        set_local_days(decode_schedule(schedule_wire()), days, events, 500, 4000)


@pytest.mark.parametrize("raw", [b"", b"\x12\x00", b"\x12\x04\x0a\x02\x08\x08"])
def test_incomplete_schedules_rejected(raw: bytes) -> None:
    """Do not expose a partial or incompatible wire schedule as editable."""
    with pytest.raises((ValueError, KeyError)):
        decode_schedule(raw)


def active_events(schedule: dict[str, Any], day: int = 0) -> list[tuple[time, float]]:
    """Return the requested active events for HA service tests."""
    return [
        (time.fromisoformat(e["Clock"]), e["Temperature"] / 100)
        for e in schedule["Days"][day]["Events"]
        if e["Active"]
    ]
