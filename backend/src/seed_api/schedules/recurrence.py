"""When a schedule runs next (D-029): every N minutes, or daily at a wall-clock time
in a timezone. Pure functions of their arguments, so they can be tested exactly."""

from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Kind = Literal["interval", "daily"]
MIN_EVERY_MINUTES = 5
MAX_EVERY_MINUTES = 7 * 24 * 60


class BadTimezone(ValueError):
    """The name is not an IANA timezone."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as e:
        raise BadTimezone(f"{name!r} is not a timezone name such as Europe/Berlin.") from e


def next_run(
    kind: Kind,
    after: datetime,
    *,
    every_minutes: int | None = None,
    at_time: time | None = None,
    timezone: str = "UTC",
) -> datetime:
    """The first run strictly after `after` (an aware datetime), in UTC. An interval
    counts from `after`; a daily time is the next one on the clock in `timezone`. A
    time that does not exist on a day the clocks jump forward runs at the first
    moment after the gap; one that happens twice runs the first time."""
    if after.tzinfo is None:
        raise ValueError("`after` must be timezone-aware")
    if kind == "interval":
        if every_minutes is None:
            raise ValueError("an interval schedule needs every_minutes")
        return (after + timedelta(minutes=every_minutes)).astimezone(UTC)
    if at_time is None:
        raise ValueError("a daily schedule needs at_time")
    tz = zone(timezone)
    day = after.astimezone(tz).date()
    for _ in range(3):  # today, tomorrow, and a spare for a day the time falls before `after`
        local = datetime.combine(day, at_time.replace(tzinfo=None), tzinfo=tz)
        # Normalise through UTC: a time in the spring-forward gap lands after it.
        candidate = local.astimezone(UTC)
        if candidate > after:
            return candidate
        day += timedelta(days=1)
    raise RuntimeError("no next run found")  # pragma: no cover - three days always suffice
