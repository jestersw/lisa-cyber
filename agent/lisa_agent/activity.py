"""Activity engine: open apps, perform activities, switch between them.

Ported from the original Linux agent (open_application / close_application /
simulate_activity / run_command and the app-selection helpers, by the agent's
original author). The behaviour - open an app, run a randomly chosen activity's
commands with human-like pauses, close it, move on - is unchanged.

Changes to fit the new package and requirements:
- no database logging (the customer asked to keep activity out of the DB; the
  OS's own audit logs record what happens). Callers get a CommandResult and may
  update heartbeat statistics themselves.
- applications are DATA, not hardcoded here: the original embedded X11/xdotool
  app definitions in Python. They now come from templates/backend, so the same
  engine works for whatever apps an operator configures.
- run_command has a timeout so a stuck command can't wedge the agent.

Security note (AppSec): run_command uses shell=True because app templates rely
on shell features (e.g. "doom || gzdoom" fallbacks). Command strings must come
only from trusted operator-authored templates, never from unvalidated input.
"""

from __future__ import annotations

import logging
import random
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("lisa-agent.activity")


@dataclass
class CommandResult:
    command: str
    success: bool
    duration: float
    stdout: str = ""
    stderr: str = ""


def run_command(command: str, timeout: float = 60.0) -> CommandResult:
    """Run a shell command, returning a structured result (never raises)."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,  # app templates are trusted operator input; see module docstring
            check=False,  # we inspect returncode ourselves
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start
        success = proc.returncode == 0
        if success:
            log.debug("ok: %s (%.2fs)", command, duration)
        else:
            log.warning("failed: %s - %s", command, proc.stderr.strip())
        return CommandResult(command, success, duration, proc.stdout[:500], proc.stderr[:500])
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        log.warning("timeout after %.0fs: %s", timeout, command)
        return CommandResult(command, False, duration, stderr="timeout")
    except OSError as exc:
        duration = time.monotonic() - start
        log.error("error: %s - %s", command, exc)
        return CommandResult(command, False, duration, stderr=str(exc))


@dataclass
class Activity:
    description: str
    commands: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Activity:
        return cls(
            description=data.get("description", "activity"),
            commands=list(data.get("commands", [])),
        )


@dataclass
class Application:
    name: str
    open_cmd: str | None = None
    close_cmd: str | None = None
    activities: list[Activity] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Application:
        return cls(
            name=name,
            open_cmd=data.get("open"),
            close_cmd=data.get("close"),
            activities=[Activity.from_dict(a) for a in data.get("activities", [])],
        )


# A runner is anything that takes a command string and returns a CommandResult.
# Injectable so the engine can be tested without spawning real processes.
Runner = Callable[[str], CommandResult]


class ActivityEngine:
    """Opens applications and performs their activities."""

    def __init__(
        self,
        runner: Runner | None = None,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.run = runner or run_command
        self.rng = rng or random.Random()
        self.sleep = sleep or time.sleep

    def open_app(self, app: Application) -> bool:
        if not app.open_cmd:
            log.warning("no open command for %s", app.name)
            return False
        log.info("opening %s", app.name)
        return self.run(app.open_cmd).success

    def close_app(self, app: Application) -> None:
        if app.close_cmd:
            log.info("closing %s", app.name)
            self.run(app.close_cmd)

    def perform_activity(self, app: Application) -> bool:
        """Pick one of the app's activities and run its commands with pauses."""
        if not app.activities:
            return False
        activity = self.rng.choice(app.activities)
        log.info("%s: %s", app.name, activity.description)
        for cmd in activity.commands:
            self.run(cmd)
            self.sleep(self.rng.uniform(1, 3))
        return True


def should_switch(elapsed: float, session_duration: float) -> bool:
    """True once the current app has been in use long enough to switch."""
    return elapsed >= session_duration


def pick_next_app(
    apps: list[Application],
    current: Application | None = None,
    rng: random.Random | None = None,
) -> Application | None:
    """Choose the next app, avoiding the current one when possible."""
    if not apps:
        return None
    rng = rng or random.Random()
    candidates = [a for a in apps if current is None or a.name != current.name]
    return rng.choice(candidates or apps)
