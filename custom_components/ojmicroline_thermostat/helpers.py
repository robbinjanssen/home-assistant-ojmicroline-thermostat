"""Helpers for WD5-series date/time values.

The WD5 API returns and expects date/times as the thermostat's local wall
clock time (e.g. "2026-12-24T00:00:00"), which is how the OJ Microline and
SWATT apps interpret them. The library parses them with the thermostat's
standard time offset and then shifts them by that offset once more, so its
datetimes are off by the offset (and ignore daylight saving time). These
helpers recover the original wall clock time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ojmicroline_thermostat.const import WD5_DATETIME_FORMAT

if TYPE_CHECKING:
    from datetime import datetime

    from ojmicroline_thermostat import Thermostat

WD5_MODEL = "OWD5"


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


def format_wd5(value: datetime | None) -> str | None:
    """Format a library datetime for sending it back to the API unchanged."""
    wall_clock = wd5_wall_clock(value)
    return None if wall_clock is None else wall_clock.strftime(WD5_DATETIME_FORMAT)
