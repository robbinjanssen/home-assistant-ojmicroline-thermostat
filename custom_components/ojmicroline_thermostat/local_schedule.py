"""Decode and update the six-slot weekly schedule of the tested WG4 firmware.

Wire weekday numbers are ISO weekdays (1 Monday through 7 Sunday). Schedule
setpoints are Celsius x100, unlike the hold setpoints which use Celsius x200.
Only known clock/temperature/active fields are edited; other fields are kept.
"""

from __future__ import annotations

import copy
import itertools
import math
from typing import TYPE_CHECKING, Any

from .local_gateway import _encode, parse, uvarint
from .schedule import MIN_GAP, SLOTS, WEEKDAYS, ScheduleError

if TYPE_CHECKING:
    from datetime import time

# These are wire format helpers shared with the local transport, not library API.
# pylint: disable=protected-access


def _replace(raw: bytes, field: int, values: list[Any]) -> bytes:
    """Replace a known field, retaining all unrelated wire bytes exactly."""
    parse(raw)  # Validate bounds before slicing the original wire fields.
    offset = index = 0
    chunks = []
    while offset < len(raw):
        start = offset
        tag, offset = uvarint(raw, offset)
        wire = tag & 7
        if wire == 0:
            _, offset = uvarint(raw, offset)
        elif wire == 2:
            size, offset = uvarint(raw, offset)
            offset += size
        else:
            offset += 4 if wire == 5 else 8
        if tag >> 3 == field:
            chunks.append(_encode(field, values[index]))
            index += 1
        else:
            chunks.append(raw[start:offset])
    if index != len(values):
        msg = "Unexpected WG4 schedule field count"
        raise ValueError(msg)
    return b"".join(chunks)


def decode_schedule(  # pylint: disable=too-many-locals
    raw: bytes,
) -> dict[str, Any]:
    """Read a complete seven-day, six-slot schedule into the HA editor format."""
    root = parse(raw)
    days: dict[int, dict[str, Any]] = {}
    for day_raw in parse(root[2][0])[1]:
        day = parse(day_raw)
        number = day[1][0]
        if number not in range(1, 8) or number in days:
            msg = "Invalid or duplicate WG4 weekday"
            raise ValueError(msg)
        events = []
        for event_raw in day[2]:
            event = parse(event_raw)
            clock = parse(event[1][0])
            hour, minute, second = (clock[n][0] for n in (1, 2, 3))
            temperature, active = event[2][0], event[3][0]
            if not (
                0 <= hour < 24
                and 0 <= minute < 60
                and 0 <= second < 60
                and isinstance(temperature, int)
                and active in (0, 1)
            ):
                msg = "Invalid WG4 schedule event"
                raise ValueError(msg)
            events.append(
                {
                    "Clock": f"{hour:02}:{minute:02}:{second:02}",
                    "Temperature": temperature,
                    "Active": bool(active),
                    "EventIsOnNextDay": False,
                }
            )
        if len(events) != SLOTS or not events[0]["Active"]:
            msg = "Expected six WG4 slots with the first slot active"
            raise ValueError(msg)
        days[number] = {"Events": events}
    if set(days) != set(range(1, 8)):
        msg = "Expected seven WG4 schedule days"
        raise ValueError(msg)
    return {"Days": [days[number] for number in range(1, 8)]}


def encode_schedule(  # pylint: disable=too-many-locals
    raw: bytes, schedule: dict[str, Any]
) -> bytes:
    """Edit known fields in a fresh device template, keeping all other bytes."""
    decode_schedule(raw)  # Refuse incompatible templates before making a command.
    if len(schedule["Days"]) != 7:
        msg = "Expected seven schedule days"
        raise ValueError(msg)
    root = parse(raw)
    week = root[2][0]
    days = []
    for day_raw in parse(week)[1]:
        day = parse(day_raw)
        events = schedule["Days"][day[1][0] - 1]["Events"]
        if len(events) != SLOTS:
            msg = "Expected six schedule slots"
            raise ValueError(msg)
        updated = []
        for event_raw, event in zip(day[2], events, strict=True):
            fields = parse(event_raw)
            clock = fields[1][0]
            for number, value in enumerate(event["Clock"].split(":"), start=1):
                clock = _replace(clock, number, [int(value)])
            edited = _replace(event_raw, 1, [clock])
            edited = _replace(edited, 2, [event["Temperature"]])
            edited = _replace(edited, 3, [int(event["Active"])])
            updated.append(edited)
        days.append(_replace(day_raw, 2, updated))
    result = _replace(raw, 2, [_replace(week, 1, days)])
    decode_schedule(result)
    return result


def set_local_days(  # pylint: disable=too-many-locals
    schedule: dict[str, Any],
    weekdays: list[str],
    events: list[tuple[time, float]],
    minimum: int,
    maximum: int,
) -> dict[str, Any]:
    """Place active events while retaining unused slots and unchanged weekdays.

    This firmware's observed clock is a same-day 24-hour clock. Cross-midnight
    events are rejected instead of assuming the WD5 next-day encoding applies.
    Prefer existing matching slots, so editing one setpoint preserves inactive
    midday events and the temperature precision of every untouched event.
    """
    if not weekdays or any(day not in WEEKDAYS for day in weekdays):
        msg = "Select at least one valid weekday."
        raise ScheduleError(msg)
    if not 1 <= len(events) <= SLOTS:
        msg = "A day needs between one and six events."
        raise ScheduleError(msg)
    previous = -MIN_GAP
    for clock, temperature in events:
        seconds = clock.hour * 3600 + clock.minute * 60
        if clock.second or clock.microsecond or clock.minute % 15:
            msg = "Schedule times must be on a quarter of an hour."
            raise ScheduleError(msg)
        if seconds < previous + MIN_GAP:
            msg = "WG4 events must increase within the same day, 15 minutes apart."
            raise ScheduleError(msg)
        if (
            not math.isfinite(temperature)
            or not minimum <= temperature * 100 <= maximum
        ):
            msg = "The schedule temperature is outside the thermostat's limits."
            raise ScheduleError(msg)
        previous = seconds
    result = copy.deepcopy(schedule)
    for weekday in weekdays:
        slots = result["Days"][WEEKDAYS.index(weekday)]["Events"]
        clocks = [f"{clock:%H:%M:%S}" for clock, _ in events]
        chosen = _best_slots(slots, clocks)
        for slot in slots:
            slot["Active"] = False
        for index, clock_string, (_, temperature) in zip(
            chosen, clocks, events, strict=True
        ):
            slots[index].update(
                Clock=clock_string,
                Temperature=round(temperature * 100),
                Active=True,
                EventIsOnNextDay=False,
            )
    return result


def _best_slots(slots: list[dict[str, Any]], clocks: list[str]) -> tuple[int, ...]:
    """Prefer matching clocks and existing active slots, keeping slot zero active."""

    def score(choice: tuple[int, ...]) -> int:
        return sum(
            10 * (slots[slot]["Clock"] == clock) + int(slots[slot]["Active"])
            for slot, clock in zip(choice, clocks, strict=True)
        )

    return max(
        (c for c in itertools.combinations(range(SLOTS), len(clocks)) if c[0] == 0),
        key=score,
    )
