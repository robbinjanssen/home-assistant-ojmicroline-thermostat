"""Energy usage of WD5 and WG4-series thermostats.

The WD5 energy usage API (as used by the apps' statistics screen) returns,
newest first:

- view type 1, date D + 1: the kWh per local hour of day D;
- view type 2, date D, history H: the kWh per day for the (H + 1) * 7 days
  before D;
- view type 4, date = today + 1 month - 1 year: the kWh per month for the last
  12 months, including the current one.

The WG4 energy usage API (as used by the "Energy Use" page of
mythermostat.info) returns, newest first:

- view "day", date D: the kWh per local hour of day D;
- view "week", date D, history H: the kWh per day of the calendar week
  (starting on Sunday) containing D and the H weeks before (at most 10);
- view "year", date Y, history H: the kWh per month of the year Y and the H
  years before.

This module turns that into today's usage for the energy sensor, and imports
the history into long-term statistics (one per thermostat) for the energy
dashboard: hourly for the last week, daily for the last 5 weeks and monthly
before that.

With a local connection the cloud only counts the reports of a thermostat
that OJ's gateway gets. What a thermostat uses while its reports stay in Home
Assistant is counted by the gateway there, and added here: to the cloud's
hours for a thermostat that the cloud hears as well, and on its own for one
that only the gateway hears.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from itertools import zip_longest
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.util import dt as dt_util

from ojmicroline_thermostat import OJMicrolineError, Thermostat
from ojmicroline_thermostat.wg4 import week_index

from .const import DOMAIN
from .helpers import thermostat_name

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from homeassistant.core import HomeAssistant

    from .coordinator import OJMicrolineDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

VIEW_HOURS = 1
VIEW_DAYS = 2
VIEW_MONTHS = 4
HOURLY_DAYS = 7  # days imported per hour
DAILY_HISTORY = 4  # 5 weeks of daily values
# Hours after midnight during which yesterday is fetched again, in case the
# last hours arrive late.
LATE_DATA_HOURS = 3


def statistic_id(thermostat: Thermostat) -> str:
    """Return the id of a thermostat's energy statistic."""
    return f"{DOMAIN}:energy_{thermostat.serial_number.lower()}"


def _usage(response: Any) -> list[float]:
    """Return all usage values of a response, newest first."""
    if response.get("ErrorCode") == 1:
        msg = "Unable to get energy usage via API."
        raise OJMicrolineError(msg)
    return [
        float(usage["EnergyKWattHour"])
        for block in response["EnergyUsage"]
        for usage in block["Usage"]
    ]


def _hour_starts(day: date, count: int) -> list[datetime]:
    """Return the UTC start of each of the day's local hours."""
    start = dt_util.start_of_local_day(day).astimezone(UTC)
    return [start + timedelta(hours=hour) for hour in range(count)]


def _hours_in(day: date) -> int:
    """Return how many hours a local day has: 23 or 25 when the clock changes."""
    start = dt_util.start_of_local_day(day)
    end = dt_util.start_of_local_day(day + timedelta(days=1))
    return round((end - start).total_seconds() / 3600)


def _local_midnight(day: date) -> datetime:
    return dt_util.start_of_local_day(day).astimezone(UTC)


def _month_start(month: date) -> date:
    return month.replace(day=1)


def _previous_month(month: date) -> date:
    return (month.replace(day=1) - timedelta(days=1)).replace(day=1)


def _year_view_date(today: date) -> date:
    """Return today + 1 month - 1 year, the date the apps use for months."""
    year, month = (
        (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
    )
    return date(year - 1, month, min(today.day, 28))


def _metadata(thermostat: Thermostat) -> StatisticMetaData:
    metadata: dict[str, Any] = {
        "has_sum": True,
        "name": f"{thermostat_name(thermostat)} energy",
        "source": DOMAIN,
        "statistic_id": statistic_id(thermostat),
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }
    try:
        # pylint: disable-next=import-outside-toplevel
        from homeassistant.components.recorder.models import (  # noqa: PLC0415
            StatisticMeanType,
        )

        metadata["mean_type"] = StatisticMeanType.NONE
    except ImportError:  # Home Assistant before 2025.5
        metadata["has_mean"] = False
    if "unit_class" in StatisticMetaData.__annotations__:
        metadata["unit_class"] = "energy"
    return metadata  # type: ignore[return-value]


class EnergyStatistics:
    """Fetches energy usage and keeps the energy statistics up to date."""

    def __init__(
        self, hass: HomeAssistant, coordinator: OJMicrolineDataUpdateCoordinator
    ) -> None:
        """Initialise."""
        self._hass = hass
        self._coordinator = coordinator
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_hourly(self, thermostat: Thermostat, day: date) -> list[float]:
        """Return the kWh per local hour of a day, oldest first."""
        if self._coordinator.wg4_api is not None:
            hours = await self._coordinator.async_fetch_wg4_energy(
                thermostat, "day", day.isoformat(), 0
            )
        else:
            hours = _usage(
                await self._coordinator.async_fetch_energy(
                    thermostat, VIEW_HOURS, day + timedelta(days=1), 0
                )
            )
        hours = list(reversed(hours))
        counted = self.counted_here(thermostat, day)
        if counted is None:
            return hours
        # The cloud counted the reports it got, the gateway the others.
        return [
            round(cloud + here, 4)
            for cloud, here in zip_longest(hours, counted, fillvalue=0.0)
        ]

    def counted_here(self, thermostat: Thermostat, day: date) -> list[float] | None:
        """Return the kWh per local hour of a day that the gateway counted.

        That is what a thermostat used while OJ's gateway did not get its
        reports, so the cloud knows nothing of it.

        Returns
        -------
            The kWh of every hour of the day, oldest first; None if the
            gateway did not count this thermostat in the last days.

        """
        local = self._coordinator.local
        usage = {} if local is None else local.usage(thermostat.serial_number)
        if not usage:
            return None
        # The gateway counts by the hour in UTC, which is the local hour
        # wherever the time zone is a whole number of hours from UTC.
        return [
            usage.get(start.replace(minute=0, second=0, microsecond=0), 0.0)
            for start in _hour_starts(day, _hours_in(day))
        ]

    async def _async_daily(self, thermostat: Thermostat, today: date) -> list[float]:
        """Return the kWh per day of the last weeks, starting with today."""
        if self._coordinator.wg4_api is not None:
            days = await self._coordinator.async_fetch_wg4_energy(
                thermostat, "week", today.isoformat(), DAILY_HISTORY
            )
            return days[week_index(today) :]

        response = await self._coordinator.async_fetch_energy(
            thermostat, VIEW_DAYS, today + timedelta(days=1), DAILY_HISTORY
        )
        return _usage(response)

    async def _async_monthly(self, thermostat: Thermostat, today: date) -> list[float]:
        """Return the kWh per month of the last 12 months, starting with this one."""
        if self._coordinator.wg4_api is not None:
            months = await self._coordinator.async_fetch_wg4_energy(
                thermostat, "year", str(today.year), 1
            )
            # This and the previous year are listed from December back to
            # January.
            current = 12 - today.month
            return months[current : current + 12]

        response = await self._coordinator.async_fetch_energy(
            thermostat, VIEW_MONTHS, _year_view_date(today), 0
        )
        return _usage(response)

    async def async_today(self, thermostat: Thermostat) -> list[float]:
        """Return today's kWh per hour so far."""
        return await self.async_hourly(thermostat, dt_util.now().date())

    def schedule_import(self, thermostat: Thermostat, today: list[float]) -> None:
        """Update the thermostat's statistics in the background."""
        self._schedule(thermostat, lambda: self._async_import_locked(thermostat, today))

    def schedule_import_counted(self, thermostat: Thermostat) -> None:
        """Write what the gateway counted to the statistics, in the background.

        This is for a thermostat that only the gateway hears: the cloud has
        nothing to add, and is not asked.
        """
        self._schedule(thermostat, lambda: self._async_import_counted(thermostat))

    def _schedule(
        self, thermostat: Thermostat, work: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        lock = self._locks.setdefault(thermostat.serial_number, asyncio.Lock())
        if lock.locked():
            return
        self._hass.async_create_background_task(
            self._async_import(lock, work),
            f"{DOMAIN} energy statistics {thermostat.serial_number}",
        )

    async def _async_import(
        self, lock: asyncio.Lock, work: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        async with lock:
            try:
                await work()
            except OJMicrolineError as error:
                _LOGGER.debug("Could not update energy statistics: %s", error)

    async def _async_import_counted(self, thermostat: Thermostat) -> None:
        """Write the hours the gateway counted, from the last hour written on.

        What the statistics hold of earlier hours stays as it is: the cloud
        may have counted those, before the thermostat was the gateway's alone.
        The last hour is written again, because it was not over yet; if the
        cloud wrote it, what the cloud counted of that one hour is lost.
        """
        local = self._coordinator.local
        points = {} if local is None else local.usage(thermostat.serial_number)
        stat_id = statistic_id(thermostat)
        last = await get_instance(self._hass).async_add_executor_job(
            get_last_statistics,
            self._hass,
            1,
            stat_id,
            True,  # noqa: FBT003
            {"state", "sum"},
        )
        total = 0.0
        if rows := last.get(stat_id):
            written = dt_util.utc_from_timestamp(rows[0]["start"])
            total = rows[0]["sum"] or 0.0
            points = {
                start: energy for start, energy in points.items() if start >= written
            }
            if written in points:
                total -= rows[0]["state"] or 0.0
        statistics = []
        for start in sorted(points):
            total += points[start]
            statistics.append(
                {
                    "start": start,
                    "state": round(points[start], 4),
                    "sum": round(total, 4),
                }
            )
        if statistics:
            async_add_external_statistics(
                self._hass,
                _metadata(thermostat),
                statistics,  # type: ignore[arg-type]
            )

    async def _async_import_locked(  # pylint: disable=too-many-locals
        self, thermostat: Thermostat, today_hours: list[float]
    ) -> None:
        stat_id = statistic_id(thermostat)
        recorder = get_instance(self._hass)
        last = await recorder.async_add_executor_job(
            get_last_statistics,
            self._hass,
            1,
            stat_id,
            True,  # noqa: FBT003
            {"sum"},
        )
        now = dt_util.now()
        today = now.date()

        if not last.get(stat_id):
            points = await self._async_backfill(thermostat, today, today_hours)
            base = 0.0
        else:
            last_start = dt_util.as_local(
                dt_util.utc_from_timestamp(last[stat_id][0]["start"])
            ).date()
            first_day = min(last_start, today)
            if now.hour < LATE_DATA_HOURS:
                first_day = min(first_day, today - timedelta(days=1))
            first_day = max(first_day, today - timedelta(days=HOURLY_DAYS - 1))
            points = {}
            day = first_day
            while day <= today:
                hours = (
                    today_hours
                    if day == today
                    else await self.async_hourly(thermostat, day)
                )
                points.update(zip(_hour_starts(day, len(hours)), hours, strict=True))
                day += timedelta(days=1)
            before = await self._async_sum_before(stat_id, _local_midnight(first_day))
            base = before if before is not None else last[stat_id][0]["sum"] or 0.0

        now_utc = dt_util.utcnow()
        statistics = []
        total = base
        for start in sorted(points):
            if start > now_utc:
                break
            total += points[start]
            statistics.append(
                {"start": start, "state": points[start], "sum": round(total, 4)}
            )
        if statistics:
            async_add_external_statistics(
                self._hass,
                _metadata(thermostat),
                statistics,  # type: ignore[arg-type]
            )

    async def _async_sum_before(self, stat_id: str, start: datetime) -> float | None:
        """Return the sum just before the given hour, from the rows after it."""
        rows = await get_instance(self._hass).async_add_executor_job(
            statistics_during_period,
            self._hass,
            start,
            None,
            {stat_id},
            "hour",
            None,
            {"sum", "state"},
        )
        found = rows.get(stat_id)
        if not found:
            return None
        total = found[0].get("sum")
        if total is None:
            return None
        return float(total) - float(found[0].get("state") or 0.0)

    async def _async_backfill(  # pylint: disable=too-many-locals
        self, thermostat: Thermostat, today: date, today_hours: list[float]
    ) -> dict[datetime, float]:
        """Return the kWh per period start for the available history."""
        points: dict[datetime, float] = {}

        # Last week per hour.
        for offset in range(HOURLY_DAYS):
            day = today - timedelta(days=offset)
            hours = (
                today_hours if offset == 0 else await self.async_hourly(thermostat, day)
            )
            points.update(zip(_hour_starts(day, len(hours)), hours, strict=True))
        first_hourly_day = today - timedelta(days=HOURLY_DAYS - 1)

        # The weeks before that per day.
        daily = await self._async_daily(thermostat, today)
        first_day = today - timedelta(days=len(daily) - 1)
        for offset, usage in enumerate(daily):
            day = today - timedelta(days=offset)
            if day < first_hourly_day:
                points[_local_midnight(day)] = usage

        # The months before that per month; the month the daily values start
        # in gets the remainder of its total.
        month = _month_start(today)
        for usage in await self._async_monthly(thermostat, today):
            if month < _month_start(first_day):
                points[_local_midnight(month)] = usage
            elif month == _month_start(first_day):
                covered = sum(
                    value
                    for start, value in points.items()
                    if _month_start(dt_util.as_local(start).date()) == month
                )
                remainder = round(usage - covered, 4)
                if remainder > 0:
                    points[_local_midnight(month)] = (
                        points.get(_local_midnight(month), 0.0) + remainder
                    )
            month = _previous_month(month)
        return points
