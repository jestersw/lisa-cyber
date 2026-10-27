from datetime import datetime

from lisa_agent.activity import Application
from lisa_agent.config import WorkSchedule
from lisa_agent.orchestrator import Agent

SCHED = WorkSchedule()  # Mon-Fri 09:00-18:00, lunch window 13:00-15:00


def dt(*args) -> datetime:
    """Build a naive local-time datetime for tests (no tz needed, see schedule.py)."""
    return datetime(*args)


class FakeClock:
    """A controllable 'now' that a test can advance step by step."""

    def __init__(self, start: datetime):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance_seconds(self, seconds: float) -> None:
        self.current = self.current.fromtimestamp(self.current.timestamp() + seconds)


class FakeEngine:
    def __init__(self):
        self.opened = []
        self.closed = []
        self.activities = 0

    def open_app(self, app):
        self.opened.append(app.name)
        return True

    def close_app(self, app):
        self.closed.append(app.name)

    def perform_activity(self, app):
        self.activities += 1
        return True


class FakeHeartbeat:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.forced = 0
        self.nudged = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def force(self):
        self.forced += 1
        return True

    def nudge(self):
        self.nudged += 1


class FakeMutex:
    def __init__(self, can_acquire=True):
        self.can_acquire = can_acquire
        self.acquired = False
        self.released = False

    def acquire(self):
        self.acquired = self.can_acquire
        return self.can_acquire

    def release(self):
        self.released = True


def make_agent(
    clock,
    *,
    stop_after_ticks=None,
    apps=None,
    schedule=None,
    next_app_provider=None,
    **agent_kwargs,
):
    apps = apps or [
        Application("editor", open_cmd="x"),
        Application("browser", open_cmd="y"),
    ]
    engine = FakeEngine()
    heartbeat = FakeHeartbeat()
    mutex = FakeMutex()

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        # Advance the fake clock a little on every sleep so state-transitions
        # (e.g. off -> working) can happen across ticks without real waiting.
        clock.advance_seconds(1)
        if stop_after_ticks is not None and sleeps["n"] >= stop_after_ticks:
            agent.stop()

    agent = Agent(
        schedule=schedule or SCHED,
        apps=apps,
        engine=engine,
        heartbeat=heartbeat,
        mutex=mutex,
        now=clock,
        sleep=fake_sleep,
        session_min=1,
        session_max=1,
        switch_pause_range=(0, 0),
        inactive_period_range=(1000, 1000),  # effectively disabled in short tests
        next_app_provider=next_app_provider,
        **agent_kwargs,
    )
    return agent, engine, heartbeat, mutex


def test_off_hours_closes_app_and_waits_without_opening_new_one():
    clock = FakeClock(dt(2024, 1, 6, 10, 0))  # Saturday -> OFF
    agent, engine, _heartbeat, mutex = make_agent(clock, stop_after_ticks=2)
    agent.start()
    assert engine.opened == []
    assert mutex.acquired is True
    assert mutex.released is True


def test_mutex_not_acquired_prevents_start():
    clock = FakeClock(dt(2024, 1, 8, 10, 0))  # Monday, working hours
    engine = FakeEngine()
    heartbeat = FakeHeartbeat()
    mutex = FakeMutex(can_acquire=False)
    agent = Agent(
        schedule=SCHED,
        apps=[Application("editor", open_cmd="x")],
        engine=engine,
        heartbeat=heartbeat,
        mutex=mutex,
        now=clock,
        sleep=lambda _s: None,
    )
    agent.start()
    assert heartbeat.started is False
    assert engine.opened == []


def test_working_hours_opens_an_app_and_performs_activity():
    clock = FakeClock(dt(2024, 1, 8, 10, 0))  # Monday, working hours
    agent, engine, heartbeat, _mutex = make_agent(clock, stop_after_ticks=8)
    agent.start()
    assert len(engine.opened) >= 1
    assert engine.activities >= 1
    assert heartbeat.started is True
    assert heartbeat.forced >= 1  # at least the initial force() on start
    # Opening an app nudges the heartbeat so the panel reflects it immediately.
    assert heartbeat.nudged >= 1


def test_shutdown_closes_current_app_and_sends_final_heartbeat():
    clock = FakeClock(dt(2024, 1, 8, 10, 0))
    agent, engine, heartbeat, mutex = make_agent(clock, stop_after_ticks=8)
    agent.start()
    # Whatever app was opened must also appear as closed by shutdown.
    if engine.opened:
        assert engine.opened[0] in engine.closed
    assert heartbeat.stopped is True
    assert mutex.released is True


def test_lunch_time_closes_app_and_does_not_reopen_during_lunch():
    # pick_lunch() randomises the window within lunch_earliest..lunch_latest, so
    # a fixed clock time isn't guaranteed to land inside it under the default
    # schedule. Use a schedule where min==max duration and the window has
    # exactly one possible start, making the lunch window deterministic.
    fixed_lunch_schedule = WorkSchedule(
        lunch_earliest="13:00",
        lunch_latest="13:45",
        lunch_min_minutes=45,
        lunch_max_minutes=45,
    )
    clock = FakeClock(dt(2024, 1, 8, 13, 20))  # inside the fixed 13:00-13:45 window
    agent, engine, _heartbeat, _mutex = make_agent(
        clock, stop_after_ticks=3, schedule=fixed_lunch_schedule
    )
    agent.start()
    # No app should be opened while stuck in the lunch window.
    assert engine.opened == []


def test_stop_is_honoured_promptly_via_interruptible_sleep():
    clock = FakeClock(dt(2024, 1, 6, 3, 0))  # Saturday, long OFF sleep
    agent, _engine, _heartbeat, mutex = make_agent(clock, stop_after_ticks=1)
    agent.start()
    # The 60s off-hours sleep is interruptible; stopping after 1 tick must not
    # block for the full duration (fake_sleep is called exactly once here).
    assert mutex.released is True


def test_next_app_provider_drives_selection():
    # The provider (e.g. the backend ML endpoint) decides which app opens next.
    apps = [Application("editor", open_cmd="x"), Application("browser", open_cmd="y")]
    clock = FakeClock(dt(2024, 1, 1, 10, 0))  # Monday, working hours

    calls = {"n": 0}

    def provider(available, _current):
        calls["n"] += 1
        return next(a for a in available if a.name == "browser")

    agent, engine, _hb, _mutex = make_agent(
        clock,
        stop_after_ticks=4,
        apps=apps,
        next_app_provider=provider,
        glance_probability=0,  # isolate switch selection from glance excursions
    )
    agent.start()

    assert calls["n"] >= 1
    assert "browser" in engine.opened
    assert "editor" not in engine.opened


def test_focus_burst_runs_several_activities():
    # Force the focus branch (glance off, focus certain): one work step should
    # perform multiple activities back-to-back. Drive one work step directly
    # (the tick-based stop in start() can't exercise a multi-activity burst).
    clock = FakeClock(dt(2024, 1, 8, 10, 0))  # Monday, working hours
    agent, engine, _hb, _mutex = make_agent(
        clock,
        apps=[Application("editor", open_cmd="x")],
        glance_probability=0.0,
        focus_probability=1.0,
    )
    agent.running = True
    agent._interruptible_sleep = lambda *_: None  # don't busy-wait in the test
    agent.current_app = agent.apps[0]
    agent._work_step()
    # A burst performs 2-4 activities in one step, vs 1 for an ordinary step.
    assert engine.activities >= 2


def test_glance_opens_another_app_without_switching():
    # Force the glance branch: the agent opens the other app, acts, closes it,
    # and the current app is unchanged.
    clock = FakeClock(dt(2024, 1, 8, 10, 0))
    apps = [Application("editor", open_cmd="x"), Application("browser", open_cmd="y")]
    agent, engine, _hb, _mutex = make_agent(
        clock,
        apps=apps,
        glance_probability=1.0,
        focus_probability=0.0,
    )
    agent.running = True
    agent._interruptible_sleep = lambda *_: None
    agent.current_app = apps[0]  # editor
    agent._work_step()
    assert "browser" in engine.opened  # the glance opened the other app
    assert "browser" in engine.closed  # and closed it again
    assert engine.activities >= 1
    assert agent.current_app is apps[0]  # the session did not switch


def test_falls_back_locally_when_provider_returns_none():
    apps = [Application("editor", open_cmd="x"), Application("browser", open_cmd="y")]
    clock = FakeClock(dt(2024, 1, 1, 10, 0))

    agent, engine, _hb, _mutex = make_agent(
        clock, stop_after_ticks=4, apps=apps, next_app_provider=lambda *_: None
    )
    agent.start()

    # Provider gave nothing, so the local fallback still opened some app.
    assert engine.opened
