"""Activity engine: open apps, perform their activities, switch between them.

Parses the full application-plugin format from the config spec
(docs/agent-config-schema.md): installation, execution, and activities whose
commands are structured objects (key / key_combination / type_text) rather than
raw shell strings. Structured commands are translated to shell via xdotool at
run time. Activity selection is weighted by each activity's `weight`.

Originally ported from the Linux agent's open/close/simulate_activity logic;
extended here to the plugin format.

Security note (AppSec): run_command uses shell=True because plugin commands rely
on shell features. Command strings come only from trusted operator-authored (or
generated-then-stored) plugins, never from unvalidated external input.
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
            shell=True,  # plugin commands are trusted operator input; see module docstring
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
class Command:
    """A single structured command inside an activity."""

    type: str
    delay: float = 0.0
    # depending on type, one of these is set:
    key: str | None = None
    keys: str | None = None
    text: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Command:
        return cls(
            type=data.get("type", ""),
            delay=float(data.get("delay", 0.0)),
            key=data.get("key"),
            keys=data.get("keys"),
            text=data.get("text"),
        )

    def to_shell(self) -> str | None:
        """Translate this command to a shell string (xdotool on Linux).

        Returns None for an unknown/unsupported type (caller skips it).
        """
        if self.type == "key" and self.key:
            return f"xdotool key {self.key}"
        if self.type == "key_combination" and self.keys:
            return f"xdotool key {self.keys}"
        if self.type == "type_text" and self.text is not None:
            # --clearmodifiers so held keys don't corrupt the typed text
            escaped = self.text.replace("'", "'\\''")
            return f"xdotool type --clearmodifiers '{escaped}'"
        return None


@dataclass
class Activity:
    id: str
    name: str
    weight: int = 1
    min_duration: float = 0.0
    max_duration: float = 0.0
    commands: list[Command] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Activity:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "activity")),
            weight=int(data.get("weight", 1)),
            min_duration=float(data.get("min_duration", 0.0)),
            max_duration=float(data.get("max_duration", 0.0)),
            commands=[Command.from_dict(c) for c in data.get("commands", [])],
        )


@dataclass
class Application:
    """A single application plugin (app_template.json format)."""

    name: str
    open_cmd: str | None = None
    close_cmd: str | None = None
    startup_delay: float = 0.0
    check_command: str | None = None
    install_commands: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    post_install_commands: list[str] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    usage_probability: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Application:
        info = data.get("app_info", {})
        install = data.get("installation", {})
        execution = data.get("execution", {})
        settings = data.get("settings", {})
        return cls(
            name=info.get("name", data.get("name", "unknown")),
            open_cmd=execution.get("open_command"),
            close_cmd=execution.get("close_command"),
            startup_delay=float(execution.get("startup_delay", 0.0)),
            check_command=install.get("check_command"),
            install_commands=list(install.get("install_commands", [])),
            dependencies=list(install.get("dependencies", [])),
            post_install_commands=list(install.get("post_install_commands", [])),
            activities=[Activity.from_dict(a) for a in data.get("activities", [])],
            usage_probability=float(settings.get("usage_probability", 1.0)),
        )


# A runner takes a command string and returns a CommandResult. Injectable so the
# engine can be tested without spawning real processes.
Runner = Callable[[str], CommandResult]


def pick_weighted_activity(activities: list[Activity], rng: random.Random) -> Activity | None:
    """Choose an activity, biased by weight. Falls back to uniform if no weights."""
    if not activities:
        return None
    weights = [max(0, a.weight) for a in activities]
    if sum(weights) <= 0:
        return rng.choice(activities)
    return rng.choices(activities, weights=weights, k=1)[0]


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
        ok = self.run(app.open_cmd).success
        if ok and app.startup_delay:
            self.sleep(app.startup_delay)
        return ok

    def close_app(self, app: Application) -> None:
        if app.close_cmd:
            log.info("closing %s", app.name)
            self.run(app.close_cmd)

    def perform_activity(self, app: Application) -> bool:
        """Pick a weighted activity and run its commands, honouring per-command delays."""
        activity = pick_weighted_activity(app.activities, self.rng)
        if activity is None:
            return False
        log.info("%s: %s", app.name, activity.name)
        for command in activity.commands:
            shell = command.to_shell()
            if shell is None:
                log.warning("unknown command type %r in %s, skipping", command.type, activity.id)
                continue
            self.run(shell)
            if command.delay:
                self.sleep(command.delay)
        return True


def should_switch(elapsed: float, session_duration: float) -> bool:
    """True once the current app has been in use long enough to switch."""
    return elapsed >= session_duration


def pick_next_app(
    apps: list[Application],
    current: Application | None = None,
    rng: random.Random | None = None,
    transition_model: dict | None = None,
) -> Application | None:
    """Choose the next app.

    If a `transition_model` is supplied and it has counts for the current
    app that overlap with `apps`, the next app is sampled weighted by those
    counts (see docs/agent-config-schema.md for the model format).

    Otherwise falls back to a uniform choice that avoids the current app
    when possible. The fallback preserves the pre-ML behaviour so agents
    without a model in their config keep working.
    """
    if not apps:
        return None
    rng = rng or random.Random()

    weighted = _weighted_next_from_model(apps, current, transition_model, rng)
    if weighted is not None:
        return weighted

    candidates = [a for a in apps if current is None or a.name != current.name]
    return rng.choice(candidates or apps)


def _weighted_next_from_model(
    apps: list[Application],
    current: Application | None,
    transition_model: dict | None,
    rng: random.Random,
) -> Application | None:
    """Try to pick the next app from the markov model. Returns None if the
    model isn't usable for this transition (missing, unknown current app,
    no overlap with available apps) so the caller can fall back."""
    if not transition_model or current is None:
        return None
    counts = transition_model.get("counts")
    if not isinstance(counts, dict):
        return None
    row = counts.get(current.name)
    if not isinstance(row, dict) or not row:
        return None

    # Only apps we actually have (and can weight positively) are candidates.
    # A model trained on a different app set is normal; we just skip the
    # names we don't recognise and use whatever overlap remains.
    apps_by_name = {a.name: a for a in apps}
    candidates: list[Application] = []
    weights: list[float] = []
    for next_name, weight in row.items():
        app = apps_by_name.get(next_name)
        if app is None:
            continue
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        candidates.append(app)
        weights.append(w)

    if not candidates:
        return None
    return rng.choices(candidates, weights=weights, k=1)[0]
