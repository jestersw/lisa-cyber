import random
from datetime import datetime, time

from lisa_agent.config import WorkSchedule
from lisa_agent.schedule import (
    State,
    current_state,
    is_work_hours,
    is_workday,
    pick_lunch,
)

SCHED = WorkSchedule()  # defaults: Mon-Fri 09:00-18:00, lunch 13:00-15:00


def dt(day: str, hhmm: str) -> datetime:
    """Helper: build a datetime for a given weekday and HH:MM.

    Anchor week starts Mon 2024-01-01, so day offsets map to weekday().
    """
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    base_day = 1 + days.index(day)  # 2024-01-01 is a Monday
    h, m = map(int, hhmm.split(":"))
    return datetime(2024, 1, base_day, h, m)  # noqa: DTZ001


def test_workday_true_on_weekdays():
    assert is_workday(dt("mon", "10:00"), SCHED)
    assert is_workday(dt("fri", "10:00"), SCHED)


def test_workday_false_on_weekend():
    assert not is_workday(dt("sat", "10:00"), SCHED)
    assert not is_workday(dt("sun", "10:00"), SCHED)


def test_work_hours_within_window():
    assert is_work_hours(dt("tue", "09:00"), SCHED)
    assert is_work_hours(dt("tue", "12:30"), SCHED)
    assert is_work_hours(dt("tue", "18:00"), SCHED)


def test_work_hours_outside_window():
    assert not is_work_hours(dt("tue", "08:59"), SCHED)
    assert not is_work_hours(dt("tue", "18:01"), SCHED)


def test_weekend_is_never_work_hours():
    assert not is_work_hours(dt("sat", "10:00"), SCHED)


def test_state_off_outside_hours():
    assert current_state(dt("mon", "07:00"), SCHED, time(13, 0), time(14, 0)) == State.OFF
    assert current_state(dt("sun", "10:00"), SCHED, time(13, 0), time(14, 0)) == State.OFF


def test_state_lunch_and_working():
    lunch_start, lunch_end = time(13, 0), time(13, 50)
    assert current_state(dt("mon", "13:20"), SCHED, lunch_start, lunch_end) == State.LUNCH
    assert current_state(dt("mon", "11:00"), SCHED, lunch_start, lunch_end) == State.WORKING
    assert current_state(dt("mon", "16:00"), SCHED, lunch_start, lunch_end) == State.WORKING


def test_pick_lunch_within_window_and_duration():
    rng = random.Random(42)
    for _ in range(200):
        start, end = pick_lunch(SCHED, rng)
        # Lunch starts no earlier than 13:00 and ends no later than 15:00.
        assert start >= time(13, 0)
        assert end <= time(15, 0)
        # Duration is within the configured 45-75 min band.
        dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        assert 45 <= dur <= 75


def test_pick_lunch_is_randomised():
    # Different seeds should generally give different lunch starts.
    a = pick_lunch(SCHED, random.Random(1))
    b = pick_lunch(SCHED, random.Random(2))
    assert a != b
