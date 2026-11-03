"""Cron expressions for people: a sentence, the next runs in the schedule's timezone and UTC, and DST warnings.

AgentOS evaluates 5-field cron expressions with ``croniter`` in the schedule's timezone, so the preview does the same:
a run at 08:00 New York time stays at 08:00 local when daylight saving ends, and moves from 12:00 to 13:00 UTC.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter  # pyright: ignore[reportMissingTypeStubs]

FIELDS = ("minute", "hour", "day", "month", "weekday")
DAY_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_ALIASES = {name[:3].lower(): index for index, name in enumerate(DAY_NAMES)} | {
    name[:3].lower(): index + 1 for index, name in enumerate(MONTH_NAMES)
}
_RANGES = {"minute": (0, 59), "hour": (0, 23), "day": (1, 31), "month": (1, 12), "weekday": (0, 7)}
_STEP = re.compile(r"^\*/(\d+)$")
_RANGE = re.compile(r"^(\w+)-(\w+)$")
DST_WINDOW = timedelta(days=14)


class CronError(ValueError):
    def __init__(self, message: str, fields: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.fields = tuple(fields)


def _value(token: str) -> int:
    lowered = token.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    return int(token)


def split(expression: str) -> tuple[str, str, str, str, str]:
    parts = expression.split()
    if len(parts) != len(FIELDS):
        raise CronError(f"A cron expression has 5 fields ({' '.join(FIELDS)}); this one has {len(parts)}.")
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def validate(expression: str) -> None:
    """Raises :class:`CronError` naming the fields that don't parse."""
    parts = split(expression)
    if croniter.is_valid(expression):  # pyright: ignore[reportUnknownMemberType]
        return
    bad = [
        name
        for index, name in enumerate(FIELDS)
        if not croniter.is_valid(" ".join(part if i == index else "*" for i, part in enumerate(parts)))  # pyright: ignore[reportUnknownMemberType]
    ]
    raise CronError(f"Invalid {', '.join(bad) or 'expression'}.", bad or FIELDS)


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"Unknown timezone {name!r}.", ("timezone",)) from exc


def _values(field: str, name: str) -> list[int] | None:
    """Explicit values of a field (``1,3`` or ``1-5``); ``None`` for ``*``, steps and anything fancier."""
    if field == "*":
        return None
    values: list[int] = []
    for part in field.split(","):
        if match := _RANGE.match(part):
            start, end = _value(match.group(1)), _value(match.group(2))
            if end < start:
                return None
            values.extend(range(start, end + 1))
        elif part.isalnum():
            values.append(_value(part))
        else:
            return None
    low, high = _RANGES[name]
    if not all(low <= value <= high for value in values):
        return None
    return sorted(set(values))


def _join(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _run(values: Sequence[int]) -> tuple[int, int] | None:
    """``(first, last)`` when the values are consecutive."""
    if len(values) > 2 and list(values) == list(range(values[0], values[-1] + 1)):  # noqa: PLR2004
        return values[0], values[-1]
    return None


def _days(field: str) -> str | None:
    values = _values(field, "weekday")
    if values is None:
        return None
    values = sorted({7 if value == 0 else value for value in values})  # Sunday last, like people write weeks
    names = [DAY_NAMES[value % 7] for value in values]
    if values == list(range(1, 6)):
        return "Monday to Friday"
    if values == [6, 7]:
        return "on weekends"
    run = _run(values)
    if run:
        return f"{DAY_NAMES[run[0] % 7]} to {DAY_NAMES[run[1] % 7]}"
    return _join(names)


def _months(field: str) -> str | None:
    values = _values(field, "month")
    if values is None:
        return None
    run = _run(values)
    if run:
        return f"{MONTH_NAMES[run[0] - 1]} to {MONTH_NAMES[run[1] - 1]}"
    return "in " + _join([MONTH_NAMES[value - 1] for value in values])


def _ordinal(day: int) -> str:
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")  # noqa: PLR2004
    return f"{day}{suffix}"


def _time_part(minute: str, hour: str) -> tuple[str, bool]:  # noqa: C901, PLR0911  (one case per cron shape)
    """``(phrase, at_fixed_times)``: "at 03:00" (fixed) or "Every 30 minutes" with an hour range."""
    minutes = _values(minute, "minute")
    hours = _values(hour, "hour")
    minute_step = _STEP.match(minute)
    hour_step = _STEP.match(hour)

    if minutes is not None and len(minutes) == 1 and hours is not None:
        if len(hours) > 6:  # noqa: PLR2004
            run = _run(hours)
            if run:
                at = "on the hour" if minutes[0] == 0 else f"at :{minutes[0]:02d}"
                return f"Every hour, {at}, {run[0]:02d}:{minutes[0]:02d}–{run[1]:02d}:{minutes[0]:02d}", False
        return "at " + _join([f"{h:02d}:{minutes[0]:02d}" for h in hours]), True
    if minutes is not None and len(minutes) == 1 and hour == "*":
        return ("Every hour, on the hour" if minutes[0] == 0 else f"Every hour at :{minutes[0]:02d}"), False
    if minutes is not None and len(minutes) == 1 and hour_step:
        every = int(hour_step.group(1))
        tail = "on the hour" if minutes[0] == 0 else f"at :{minutes[0]:02d}"
        return (f"Every {every} hours, {tail}" if every > 1 else f"Every hour, {tail}"), False

    if minute == "*" or minute_step:
        every = int(minute_step.group(1)) if minute_step else 1
        phrase = "Every minute" if every == 1 else f"Every {every} minutes"
        if hour == "*":
            return phrase, False
        if hours is not None:
            run = _run(hours) or ((hours[0], hours[0]) if len(hours) == 1 else None)
            if run:
                return f"{phrase}, {run[0]:02d}:00–{run[1]:02d}:59", False
            return f"{phrase} during {_join([f'{h:02d}:00' for h in hours])} hours", False
    if minutes is not None and hour == "*":
        return f"Every hour at minutes {_join([str(m) for m in minutes])}", False
    raise CronError("not describable")


def _parts(expression: str) -> tuple[str, bool, str | None, list[int] | None, str | None] | None:
    """The describable pieces (time phrase, fixed, weekdays, days of month, months), or ``None``."""
    minute, hour, day, month, weekday = split(expression)
    try:
        time_phrase, fixed = _time_part(minute, hour)
        days = _days(weekday) if weekday != "*" else None
        dom = _values(day, "day") if day != "*" else None
        months = _months(month) if month != "*" else None
    except CronError, ValueError, IndexError:
        return None
    if (weekday != "*" and days is None) or (day != "*" and dom is None) or (month != "*" and months is None):
        return None
    return time_phrase, fixed, days, dom, months


def describe(expression: str) -> str:
    """The expression as a sentence: "Every day at 03:00", "Every Monday at 07:30"."""
    parts = _parts(expression)
    if parts is None:
        return f"Custom schedule: {expression}"
    time_phrase, fixed, days, dom, months = parts

    if fixed:
        if (
            days
            and dom is None
            and "," not in days
            and " to " not in days
            and " and " not in days
            and days != "on weekends"
        ):
            sentence = f"Every {days} {time_phrase}"
        elif dom is not None:
            sentence = f"On the {_join([_ordinal(d) for d in dom])} of the month {time_phrase}"
        elif days:
            sentence = f"{days[0].upper()}{days[1:]} {time_phrase}"
        else:
            sentence = f"Every day {time_phrase}"
    else:
        sentence = time_phrase
        if dom is not None:
            sentence += f", on the {_join([_ordinal(d) for d in dom])} of the month"
        if days:
            sentence += f", {days}"
    if months:
        sentence += f", {months}"
    return sentence


@dataclass(frozen=True, slots=True)
class Run:
    local: datetime
    utc: datetime


@dataclass(frozen=True, slots=True)
class Preview:
    expression: str
    timezone: str
    description: str
    runs: list[Run]
    notes: list[str]


def next_runs(expression: str, timezone: str, start: datetime, count: int) -> list[Run]:
    validate(expression)
    tz = zone(timezone)
    iterator = croniter(expression, start.astimezone(tz))  # pyright: ignore[reportUnknownVariableType]
    runs: list[Run] = []
    for _ in range(count):
        moment: datetime = iterator.get_next(datetime)  # pyright: ignore[reportUnknownMemberType]
        runs.append(Run(local=moment, utc=moment.astimezone(UTC)))
    return runs


def _transitions(tz: ZoneInfo, start: datetime, end: datetime) -> list[tuple[datetime, timedelta, timedelta]]:
    """``(instant, offset before, offset after)`` for every UTC-offset change between ``start`` and ``end``."""
    found: list[tuple[datetime, timedelta, timedelta]] = []
    cursor = start.astimezone(UTC)
    step = timedelta(hours=1)
    previous = cursor.astimezone(tz).utcoffset()
    while cursor < end:
        nxt = cursor + step
        offset = nxt.astimezone(tz).utcoffset()
        if offset != previous and previous is not None and offset is not None:
            found.append((nxt, previous, offset))
        previous = offset
        cursor = nxt
    return found


def dst_notes(runs: Sequence[Run], timezone: str, start: datetime) -> list[str]:
    """What daylight saving does to these runs: their UTC time moves, and runs in the changed hour."""
    if not runs:
        return []
    tz = zone(timezone)
    end = max(runs[-1].utc, start + DST_WINDOW)
    notes: list[str] = []
    for instant, before, after in _transitions(tz, start, end):
        local_day = instant.astimezone(tz)
        verb = "ends" if after < before else "starts"
        later = next((run for run in runs if run.utc >= instant), None)
        when = f"{local_day.strftime('%a')} {local_day.day} {local_day.strftime('%b')}"
        if later is not None:
            old_utc = (later.local.replace(tzinfo=None) - before).strftime("%H:%M")
            new_utc = later.utc.strftime("%H:%M")
            notes.append(
                f"Daylight saving {verb} {when} in {timezone}: these runs move from {old_utc} to {new_utc} UTC."
            )
        else:
            notes.append(f"Daylight saving {verb} {when} in {timezone}: run times in UTC shift by an hour.")
        locals_seen: set[str] = set()
        for run in runs:
            key = run.local.strftime("%Y-%m-%d %H:%M")
            if key in locals_seen:
                notes.append(
                    f"{run.local.strftime('%H:%M')} happens twice on {when}: the schedule runs at both "
                    f"({timezone} repeats that hour)."
                )
                break
            locals_seen.add(key)
    return notes


def preview(expression: str, timezone: str, *, start: datetime, count: int = 5) -> Preview:
    expression = " ".join(expression.split())
    runs = next_runs(expression, timezone, start, count)
    return Preview(
        expression=expression,
        timezone=timezone,
        description=describe(expression),
        runs=runs,
        notes=dst_notes(runs, timezone, start),
    )
