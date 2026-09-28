"""Read and modify WD5-series weekly schedules.

A schedule has 7 days (Monday first), each with exactly 6 events (slots).
Slot 0 is always active; slots 1-5 can be switched on or off. Every slot
has its own allowed time window, and the last slots may run past midnight
("EventIsOnNextDay"). These rules match the schedule editor in the
OJ Microline and SWATT apps.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime, time

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

SLOTS = 6
DAY = 86400
MIN_GAP = 900  # 15 minutes
# Allowed start time window per slot, in seconds from midnight.
SLOT_MIN_TIME = [0, 1800, 3600, 5400, 7200, 14400]
SLOT_MAX_TIME = [79200, 81000, 82800, 84600, 86400, 97200]
MIN_TEMPERATURE = 5.0
MAX_TEMPERATURE = 40.0


class ScheduleError(ValueError):
    """Raised when a requested schedule is not valid."""


def _event_seconds(event: dict[str, Any]) -> int:
    hours, minutes, seconds = (int(part) for part in event["Clock"].split(":"))
    value = hours * 3600 + minutes * 60 + seconds
    return value + DAY if event.get("EventIsOnNextDay") else value


def _set_event_seconds(event: dict[str, Any], value: int) -> None:
    event["EventIsOnNextDay"] = value >= DAY
    value %= DAY
    event["Clock"] = f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"


def _format_seconds(value: int) -> str:
    value %= DAY
    return f"{value // 3600:02d}:{value % 3600 // 60:02d}"


def _active_events(day: dict[str, Any]) -> list[tuple[int, float]]:
    """Return (seconds, temperature °C) for the day's active events."""
    return [
        (_event_seconds(event), event["Temperature"] / 100)
        for event in day["Events"]
        if event["Active"]
    ]


def schedule_attributes(schedule: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return the active events per weekday, for use as state attributes."""
    attributes: dict[str, list[dict[str, Any]]] = {}
    for name, day in zip(WEEKDAYS, schedule["Days"], strict=False):
        events = []
        for seconds, temperature in _active_events(day):
            event: dict[str, Any] = {
                "time": _format_seconds(seconds),
                "temperature": temperature,
            }
            if seconds >= DAY:
                event["next_day"] = True
            events.append(event)
        attributes[name] = events
    return attributes


def current_setpoint(schedule: dict[str, Any], now: datetime) -> float | None:
    """Return the temperature the schedule prescribes at the given local time."""
    days = schedule["Days"]
    today = now.weekday()
    now_seconds = now.hour * 3600 + now.minute * 60 + now.second
    timeline = [
        (seconds - DAY, temperature)
        for seconds, temperature in _active_events(days[(today - 1) % 7])
    ] + _active_events(days[today])
    current = None
    for seconds, temperature in sorted(timeline):
        if seconds <= now_seconds:
            current = temperature
    return current


def set_days(  # pylint: disable=too-many-locals
    schedule: dict[str, Any],
    weekdays: list[str],
    events: list[tuple[time, float]],
) -> dict[str, Any]:
    """Return a copy of the schedule with the events set on the given weekdays.

    Events are given in chronological order; a time earlier than the previous
    one is taken to be after midnight. They are placed in the lowest
    slots whose time windows allow them; the remaining slots are switched off.

    Raises
    ------
        ScheduleError: The events do not fit the thermostat's rules.

    """
    if not 1 <= len(events) <= SLOTS:
        msg = f"A day needs between 1 and {SLOTS} events."
        raise ScheduleError(msg)

    placed: list[tuple[int, int, int]] = []  # (slot, seconds, temperature)
    previous = None
    slot = -1
    for index, (event_time, temperature) in enumerate(events):
        if event_time.second or event_time.minute % 15:
            msg = f"{event_time:%H:%M}: times must be on a quarter of an hour."
            raise ScheduleError(msg)
        if not MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE:
            msg = (
                f"{temperature}°C: temperatures must be between "
                f"{MIN_TEMPERATURE:g} and {MAX_TEMPERATURE:g}°C."
            )
            raise ScheduleError(msg)

        seconds = event_time.hour * 3600 + event_time.minute * 60
        if previous is not None and seconds < previous % DAY:
            seconds += DAY
        if previous is not None and seconds < previous + MIN_GAP:
            msg = f"{event_time:%H:%M}: events must be at least 15 minutes apart."
            raise ScheduleError(msg)

        remaining = len(events) - index - 1
        slot = next(
            (
                candidate
                for candidate in range(slot + 1, SLOTS - remaining)
                if SLOT_MIN_TIME[candidate] <= seconds <= SLOT_MAX_TIME[candidate]
                and (index > 0 or candidate == 0)
            ),
            -1,
        )
        if slot == -1:
            msg = _slot_error(index, seconds)
            raise ScheduleError(msg)
        placed.append((slot, seconds, round(temperature * 100)))
        previous = seconds

    new_schedule = copy.deepcopy(schedule)
    for weekday in weekdays:
        day = new_schedule["Days"][WEEKDAYS.index(weekday)]
        for event in day["Events"]:
            event["Active"] = False
        for slot, seconds, temperature in placed:
            event = day["Events"][slot]
            event["Active"] = True
            event["Temperature"] = temperature
            _set_event_seconds(event, seconds)

    _validate_day_transitions(new_schedule, [WEEKDAYS.index(day) for day in weekdays])
    return new_schedule


def _slot_error(index: int, seconds: int) -> str:
    if index == 0:
        return (
            f"{_format_seconds(seconds)}: the first event of a day must be "
            f"between 00:00 and {_format_seconds(SLOT_MAX_TIME[0])}."
        )
    return (
        f"{_format_seconds(seconds)}: this event does not fit the thermostat's "
        "time windows (the last event can be at 03:00 the next day at the latest)."
    )


def _validate_day_transitions(schedule: dict[str, Any], changed: list[int]) -> None:
    """Ensure events after midnight end before the next day's first event.

    Only the transitions into and out of the changed days are checked.
    """
    days = schedule["Days"]
    for index in sorted({i for day in changed for i in ((day - 1) % 7, day)}):
        events = _active_events(days[index])
        next_events = _active_events(days[(index + 1) % 7])
        if not events or not next_events:
            continue
        last = max(seconds for seconds, _ in events)
        first_next = min(seconds for seconds, _ in next_events) + DAY
        if last + MIN_GAP > first_next:
            msg = (
                f"The last event on {WEEKDAYS[index]} "
                f"({_format_seconds(last)}) must be at least 15 minutes before "
                f"the first event on {WEEKDAYS[(index + 1) % 7]} "
                f"({_format_seconds(first_next)})."
            )
            raise ScheduleError(msg)
