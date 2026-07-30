"""Work-schedule logic: decide what the simulated employee should be doing now.

Pure functions of the current time and the configured schedule - no I/O, no
side effects - so this module is fully unit-testable without X11, a DB, or a
network. Ported and corrected from the original Linux agent, which only checked
the time of day and would happily 'work' on weekends.
"""

from __future__ import annotations

import random
from datetime import datetime, time
from enum import Enum

from lisa_agent.config import WorkSchedule


class State(str, Enum):
    WORKING = "working"
    LUNCH = "lunch"
    OFF = "off"  # outside work hours or a non-working day


def _parse(hhmm: str) -> time:
    return datetime.strptime(hhmm, "%H:%M").time()  # noqa: DTZ007


def is_workday(now: datetime, schedule: WorkSchedule) -> bool:
    return now.weekday() in schedule.workdays


def is_work_hours(now: datetime, schedule: WorkSchedule) -> bool:
    """True if now is a working day AND within start..end."""
    if not is_workday(now, schedule):
        return False
    return _parse(schedule.start) <= now.time() <= _parse(schedule.end)


def current_state(
    now: datetime, schedule: WorkSchedule, lunch_start: time, lunch_end: time
) -> State:
    """Classify the current moment.

    lunch_start/lunch_end are decided once per day by pick_lunch() so that the
    break lands at a randomised time and length within the configured window.
    """
    if not is_work_hours(now, schedule):
        return State.OFF
    if lunch_start <= now.time() <= lunch_end:
        return State.LUNCH
    return State.WORKING


def pick_lunch(schedule: WorkSchedule, rng: random.Random | None = None) -> tuple[time, time]:
    """Choose today's lunch start and end within the configured window.

    Randomised so the employee doesn't break at exactly the same minute daily.
    Pass a seeded rng in tests for determinism.
    """
    rng = rng or random.Random()
    earliest = _parse(schedule.lunch_earliest)
    latest = _parse(schedule.lunch_latest)

    earliest_min = earliest.hour * 60 + earliest.minute
    latest_min = latest.hour * 60 + latest.minute
    duration = rng.randint(schedule.lunch_min_minutes, schedule.lunch_max_minutes)

    # Latest possible start so lunch still ends within the window.
    latest_start = max(earliest_min, latest_min - duration)
    start_min = rng.randint(earliest_min, latest_start)
    end_min = start_min + duration

    return (
        time(hour=start_min // 60, minute=start_min % 60),
        time(hour=end_min // 60, minute=end_min % 60),
    )
