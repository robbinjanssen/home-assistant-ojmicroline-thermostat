"""Helpers for WD5-series date/time values.

The WD5 API returns and expects date/times as the thermostat's local wall
clock time (e.g. "2026-12-24T00:00:00"), which is how the OJ Microline and
SWATT apps interpret them. The library parses them with the thermostat's
standard time offset and then shifts them by that offset once more, so its
datetimes are off by the offset (and ignore daylight saving time). These
helpers recover the original wall clock time.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ojmicroline_thermostat.const import REGULATION_SCHEDULE, WD5_DATETIME_FORMAT

if TYPE_CHECKING:
    from ojmicroline_thermostat import Thermostat

WD5_MODEL = "OWD5"
DAY_SECONDS = 86400


def is_wd5(thermostat: Thermostat) -> bool:
    """Return whether the thermostat is a WD5-series thermostat."""
    return thermostat.model == WD5_MODEL


def wd5_wall_clock(value: datetime | None) -> datetime | None:
    """Return the naive wall clock time the API sent for a library datetime."""
    if value is None:
        return None
    offset = value.utcoffset()
    if offset is not None:
        # The library subtracts a positive offset and adds a negative one.
        value += abs(offset)
    return value.replace(tzinfo=None)


def wd5_local_time(value: datetime | None) -> datetime | None:
    """Return a library datetime as an aware datetime in the local time zone."""
    wall_clock = wd5_wall_clock(value)
    if wall_clock is None:
        return None
    return wall_clock.replace(tzinfo=dt_util.get_default_time_zone())


def wd5_date(value: datetime | None) -> date | None:
    """Return the date of a library datetime as the API sent it."""
    wall_clock = wd5_wall_clock(value)
    return None if wall_clock is None else wall_clock.date()


def format_wd5(value: datetime | None) -> str | None:
    """Format a library datetime for sending it back to the API unchanged."""
    wall_clock = wd5_wall_clock(value)
    return None if wall_clock is None else wall_clock.strftime(WD5_DATETIME_FORMAT)


def format_wd5_date(value: date) -> str:
    """Format a date as midnight wall clock time for the API."""
    return datetime(value.year, value.month, value.day).strftime(  # noqa: DTZ001
        WD5_DATETIME_FORMAT
    )


def target_temperature(thermostat: Thermostat) -> int:
    """Return the target temperature in 1/100 °C.

    In schedule mode the library compares a WD5 thermostat's schedule with
    the UTC time instead of the local time, so the target lags by the time
    zone offset (two hours in Central European summer time).
    """
    if (
        is_wd5(thermostat)
        and thermostat.regulation_mode == REGULATION_SCHEDULE
        and thermostat.schedule
    ):
        scheduled = scheduled_temperature(thermostat.schedule, dt_util.now())
        if scheduled is not None:
            return scheduled
    return thermostat.get_target_temperature()


def scheduled_temperature(schedule: dict[str, Any], now: datetime) -> int | None:
    """Return the temperature (1/100 °C) a WD5 schedule prescribes at a local time."""
    events: dict[int, list[tuple[int, int]]] = {}
    for day in schedule["Days"]:
        # WeekDayGrpNo 1 is Monday; 7 (or 0) is Sunday.
        weekday = (day["WeekDayGrpNo"] - 1) % 7
        events[weekday] = []
        for event in day["Events"]:
            if not event["Active"]:
                continue
            hours, minutes, seconds = (int(part) for part in event["Clock"].split(":"))
            start = hours * 3600 + minutes * 60 + seconds
            if event.get("EventIsOnNextDay"):
                start += DAY_SECONDS
            events[weekday].append((start, event["Temperature"]))

    today = now.weekday()
    now_seconds = now.hour * 3600 + now.minute * 60 + now.second
    timeline = [
        (start - DAY_SECONDS, temperature)
        for start, temperature in events.get((today - 1) % 7, [])
    ] + events.get(today, [])
    current = None
    for start, temperature in sorted(timeline):
        if start <= now_seconds:
            current = temperature
    return current
