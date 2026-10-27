"""Orchestrator: wires schedule + mutex + activity + heartbeat into the agent's
main loop.

Ported from the original Linux agent's run() method (by the agent's original
author): work/lunch/off state checks, periodic simulated-inactivity breaks,
app switching with pauses, and an interruptible sleep (checks the stop flag
every second instead of blocking a full pause) so shutdown is prompt. Signal
handling (SIGTERM/SIGINT -> graceful shutdown) is kept.

This module contains no I/O specifics of its own - it drives the Config,
AgentMutex, ActivityEngine and HeartbeatLoop objects built in main.py, which
keeps it unit-testable with fakes for all of them.
"""

from __future__ import annotations

import logging
import random
import signal
import time
from collections.abc import Callable
from datetime import datetime
from datetime import time as dtime

from lisa_agent.activity import Application, pick_next_app, should_switch
from lisa_agent.config import WorkSchedule
from lisa_agent.schedule import State, current_state, pick_lunch

log = logging.getLogger("lisa-agent.orchestrator")


class Agent:
    """Runs the simulated-employee loop until stopped."""

    def __init__(
        self,
        schedule: WorkSchedule,
        apps: list[Application],
        engine,  # ActivityEngine - untyped to keep this module import-light
        heartbeat,  # HeartbeatLoop | None
        events=None,  # EventReporter | None - live activity feed (#232)
        mutex=None,  # AgentMutex | None
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
        session_min: int = 300,
        session_max: int = 1800,
        switch_pause_range: tuple[int, int] = (5, 20),
        inactive_period_range: tuple[int, int] = (10, 20),
        focus_probability: float = 0.35,
        glance_probability: float = 0.3,
        transition_model: dict | None = None,
        next_app_provider: Callable[[list[Application], Application | None], Application | None]
        | None = None,
    ) -> None:
        self.schedule = schedule
        self.apps = apps
        self.engine = engine
        self.heartbeat = heartbeat
        self.events = events
        self.mutex = mutex
        self.now = now or datetime.now
        self.sleep = sleep or time.sleep
        self.rng = rng or random.Random()
        self.session_min = session_min
        self.session_max = session_max
        self.switch_pause_range = switch_pause_range
        self.inactive_period_range = inactive_period_range
        # Work-cycle branching: within a session the agent sometimes settles into
        # a focus burst (several activities in quick succession) or glances at
        # another app and comes straight back. Both produce real events, so the
        # activity chain shows richer, branching behaviour instead of a flat
        # one-activity-per-tick line. Probabilities are per work step; the
        # remainder is an ordinary single activity.
        self.focus_probability = focus_probability
        self.glance_probability = glance_probability
        # Optional markov model that drives pick_next_app when present.
        # See docs/agent-config-schema.md for the format; agent uses only
        # `counts` — `trained_on` and `version` are for operator debugging.
        self.transition_model = transition_model
        # Optional live next-app source (the backend ML endpoint, #57). When it
        # returns None — backend unreachable or no model — we fall back to the
        # local pick_next_app below, so the agent never depends on the network.
        self.next_app_provider = next_app_provider

        self.running = False
        self.current_app: Application | None = None
        self.session_started: float = 0.0
        self.session_duration: float = 0.0
        self._activity_counter = 0
        self._next_inactive_check = self.rng.randint(*inactive_period_range)
        self._lunch_day: datetime.date | None = None
        self._lunch_window: tuple[dtime, dtime] = (dtime(13, 0), dtime(13, 0))

    # -- lifecycle -----------------------------------------------------

    def install_signal_handlers(self) -> None:
        """Route termination signals to a graceful stop (skip in non-main threads).

        The available signals differ by OS: SIGINT exists everywhere; SIGTERM
        is POSIX (how the mutex replaces a previous copy, and how a service
        manager stops the agent); SIGBREAK is the Windows Ctrl+Break / taskkill
        signal. We register whichever ones the platform defines so shutdown is
        graceful on every OS.
        """
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, lambda *_: self.stop())
            except (ValueError, OSError):
                # ValueError: not the main thread. OSError: signal unsupported
                # on this platform despite being defined. Neither is fatal.
                log.debug("could not install handler for %s", name)

    def start(self) -> None:
        if self.mutex is not None and not self.mutex.acquire():
            log.error("Could not acquire mutex; another instance may be running")
            return
        self.running = True
        if self.heartbeat is not None:
            self.heartbeat.start()
            self.heartbeat.force()
        if self.events is not None:
            self.events.start()
        log.info("Agent starting")
        try:
            self._run_loop()
        finally:
            self._shutdown()

    def stop(self) -> None:
        log.info("Stop requested")
        self.running = False

    # -- internals -------------------------------------------------------

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in 1s increments so a stop request is honoured promptly."""
        end = time.monotonic() + seconds
        while self.running and time.monotonic() < end:
            self.sleep(1)

    def _today_lunch(self, today: datetime) -> tuple[dtime, dtime]:
        if self._lunch_day != today.date():
            self._lunch_day = today.date()
            self._lunch_window = pick_lunch(self.schedule, self.rng)
        return self._lunch_window

    def _set_current_app(self, app: Application | None) -> None:
        """Set the current app and tell the backend right away.

        Nudging the heartbeat on every switch means the panel's live view
        reflects the current app immediately, instead of waiting out the
        heartbeat interval (which can be many minutes).
        """
        self.current_app = app
        if self.heartbeat is not None:
            self.heartbeat.nudge()

    def _run_loop(self) -> None:
        while self.running:
            now = self.now()
            lunch_start, lunch_end = self._today_lunch(now)
            state = current_state(now, self.schedule, lunch_start, lunch_end)

            if state == State.OFF:
                if self.current_app is not None:
                    self.engine.close_app(self.current_app)
                    self._set_current_app(None)
                self._interruptible_sleep(60)
                continue

            if state == State.LUNCH:
                if self.current_app is not None:
                    log.info("Lunch time, closing current application")
                    self.engine.close_app(self.current_app)
                    self._set_current_app(None)
                self._interruptible_sleep(60)
                continue

            # Periodic simulated-inactivity break (stepping away, etc.)
            self._activity_counter += 1
            if self._activity_counter >= self._next_inactive_check:
                self._activity_counter = 0
                self._next_inactive_check = self.rng.randint(*self.inactive_period_range)
                if self.events is not None and self.current_app is not None:
                    self.events.record(
                        self.current_app.name, "idle", context={"reason": "stepped_away"}
                    )
                self._interruptible_sleep(self.rng.uniform(30, 120))
                continue

            if should_switch(time.monotonic() - self.session_started, self.session_duration):
                if self.current_app is not None:
                    self.engine.close_app(self.current_app)
                pause = self.rng.randint(*self.switch_pause_range)
                self._interruptible_sleep(pause)
                if not self.running:
                    break

                next_app = None
                if self.next_app_provider is not None:
                    try:
                        next_app = self.next_app_provider(self.apps, self.current_app)
                    except Exception:
                        # A flaky provider must never stop the loop; fall back locally.
                        log.debug("next_app_provider raised, falling back locally", exc_info=True)
                if next_app is None:
                    next_app = pick_next_app(
                        self.apps,
                        self.current_app,
                        self.rng,
                        transition_model=self.transition_model,
                    )
                if next_app and self.engine.open_app(next_app):
                    self._set_current_app(next_app)
                    self.session_started = time.monotonic()
                    self.session_duration = self.rng.randint(self.session_min, self.session_max)
                    self.sleep(5)  # give the app time to open

            if self.current_app is not None:
                self._work_step()
            else:
                self.sleep(5)

    def _work_step(self) -> None:
        """Do one unit of work on the current app, with branching.

        Rolls once per step: a focus burst (several activities back-to-back), a
        glance at another app and back, or — most often — a single activity.
        Each branch drives real engine calls, so the activity chain reflects the
        shape of the work rather than a uniform drip of events.
        """
        app = self.current_app
        if app is None:
            self.sleep(5)
            return

        roll = self.rng.random()
        if roll < self.glance_probability and len(self.apps) > 1:
            self._glance()
        elif roll < self.glance_probability + self.focus_probability:
            # Focus burst: a short run of activities with tight gaps.
            for _ in range(self.rng.randint(2, 4)):
                if not self.running:
                    return
                self.engine.perform_activity(app)
                self._interruptible_sleep(self.rng.randint(2, 8))
        else:
            self.engine.perform_activity(app)
            self._interruptible_sleep(self.rng.randint(5, 30))

    def _glance(self) -> None:
        """Briefly open another app, do one thing, and return to the current one.

        A quick context-switch (check chat, glance at a browser tab) that leaves
        the current app unchanged — it shows up as a short branch off the main
        chain rather than a full session switch.
        """
        others = [a for a in self.apps if a is not self.current_app]
        if not others:
            self.engine.perform_activity(self.current_app)
            return
        other = self.rng.choice(others)
        if self.engine.open_app(other):
            self.engine.perform_activity(other)
            self.engine.close_app(other)
        self._interruptible_sleep(self.rng.randint(3, 10))

    def _shutdown(self) -> None:
        log.info("Shutting down")
        if self.current_app is not None:
            self.engine.close_app(self.current_app)
        if self.heartbeat is not None:
            self.heartbeat.force()  # final status report
            self.heartbeat.stop()
        if self.events is not None:
            self.events.stop()  # flushes any buffered events on the way out
        if self.mutex is not None:
            self.mutex.release()
