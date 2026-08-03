"""Deployment package loader.

The agent runs autonomously on the target VM: it does NOT fetch its config or
plugins from the backend at runtime. Instead the whole deployment package
(agent config + every application plugin it needs) is delivered together at
build/deploy time and read from a local JSON file at startup.

This module reads that JSON, validates it, and turns it into Python objects
(AgentIdentity, AgentSchedule, list[Application]). The format is defined in
docs/agent-config-schema.md sections 1-3.

Missing-plugin rule: if `applications` names an app that has no entry in
application_plugins, log a warning and skip it - the agent must not crash.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lisa_agent.activity import Application

log = logging.getLogger("lisa-agent.package")


class PackageError(ValueError):
    """The deployment package is malformed or missing required fields."""


@dataclass(frozen=True)
class AgentIdentity:
    """Who this agent is - filled in when the config is generated."""

    agent_id: str
    name: str
    role: str
    os_type: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentIdentity:
        try:
            return cls(
                agent_id=str(data["agent_id"]),
                name=str(data["name"]),
                role=str(data["role"]),
                os_type=str(data["os_type"]),
            )
        except KeyError as exc:
            raise PackageError(f"agent_info missing required field: {exc.args[0]}") from exc


@dataclass(frozen=True)
class LunchWindow:
    earliest: str = "13:00"
    latest: str = "15:00"
    min_minutes: int = 45
    max_minutes: int = 75

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LunchWindow:
        data = data or {}
        return cls(
            earliest=str(data.get("earliest", "13:00")),
            latest=str(data.get("latest", "15:00")),
            min_minutes=int(data.get("min_minutes", 45)),
            max_minutes=int(data.get("max_minutes", 75)),
        )


@dataclass(frozen=True)
class AgentSchedule:
    """This particular agent's work hours (may be randomised at generation time)."""

    workdays: tuple[int, ...] = (1, 2, 3, 4, 5)  # ISO weekdays, Mon-Fri
    work_start: str = "09:00"
    work_end: str = "18:00"
    lunch: LunchWindow = field(default_factory=LunchWindow)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AgentSchedule:
        data = data or {}
        return cls(
            workdays=tuple(int(d) for d in data.get("workdays", [1, 2, 3, 4, 5])),
            work_start=str(data.get("work_start", "09:00")),
            work_end=str(data.get("work_end", "18:00")),
            lunch=LunchWindow.from_dict(data.get("lunch")),
        )


@dataclass(frozen=True)
class Range:
    min: float
    max: float

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, default: tuple[float, float]) -> Range:
        data = data or {}
        return cls(
            min=float(data.get("min", default[0])),
            max=float(data.get("max", default[1])),
        )


@dataclass(frozen=True)
class BehaviorConfig:
    """Runtime ranges the orchestrator draws from at each step."""

    session_duration: Range = field(default_factory=lambda: Range(300, 900))
    app_switch_pause: Range = field(default_factory=lambda: Range(30, 120))
    inactive_period: Range = field(default_factory=lambda: Range(10, 20))

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BehaviorConfig:
        data = data or {}
        return cls(
            session_duration=Range.from_dict(data.get("session_duration"), default=(300, 900)),
            app_switch_pause=Range.from_dict(data.get("app_switch_pause"), default=(30, 120)),
            inactive_period=Range.from_dict(data.get("inactive_period"), default=(10, 20)),
        )


@dataclass(frozen=True)
class HeartbeatConfig:
    interval_minutes: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HeartbeatConfig:
        data = data or {}
        return cls(interval_minutes=int(data.get("interval_minutes", 30)))


@dataclass
class DeploymentPackage:
    """Everything the agent needs to run - loaded once at startup."""

    identity: AgentIdentity
    schedule: AgentSchedule
    behavior: BehaviorConfig
    heartbeat: HeartbeatConfig
    applications: list[Application]
    # Optional markov model of app-to-app transitions, produced by the
    # backend and consumed by pick_next_app. Stored as the raw dict so
    # activity.py can read `counts` without importing extra types.
    # None -> uniform random fallback. See docs/agent-config-schema.md.
    transition_model: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeploymentPackage:
        if not isinstance(data, dict):
            raise PackageError("deployment package must be a JSON object at the top level")

        agent_config = data.get("agent_config")
        if not isinstance(agent_config, dict):
            raise PackageError("missing or invalid 'agent_config'")

        plugins = data.get("application_plugins", {})
        if not isinstance(plugins, dict):
            raise PackageError("'application_plugins' must be an object keyed by app name")

        app_names = agent_config.get("applications", [])
        if not isinstance(app_names, list):
            raise PackageError("agent_config.applications must be a list of names")

        applications: list[Application] = []
        for name in app_names:
            plugin = plugins.get(name)
            if plugin is None:
                # Missing-plugin rule: warn and skip, do not crash.
                log.warning("no plugin for %r in package, skipping", name)
                continue
            try:
                applications.append(Application.from_dict(plugin))
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                log.error("plugin for %r is malformed, skipping: %s", name, exc)

        return cls(
            identity=AgentIdentity.from_dict(agent_config.get("agent_info", {})),
            schedule=AgentSchedule.from_dict(agent_config.get("schedule")),
            behavior=BehaviorConfig.from_dict(agent_config.get("behavior")),
            heartbeat=HeartbeatConfig.from_dict(agent_config.get("heartbeat")),
            applications=applications,
            transition_model=_transition_model_from(agent_config.get("transition_model")),
        )

    @classmethod
    def load(cls, path: str | Path) -> DeploymentPackage:
        """Load a package from a JSON file on disk."""
        text = Path(path).read_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PackageError(f"deployment package is not valid JSON: {exc}") from exc
        return cls.from_dict(data)


def _transition_model_from(raw: object) -> dict[str, Any] | None:
    """Accept the transition_model field verbatim if it's a dict, drop it
    otherwise. We don't validate the model's inner shape here — pick_next_app
    is defensive about missing keys / wrong types, so a garbled model gracefully
    falls back to uniform choice instead of crashing at startup."""
    if isinstance(raw, dict):
        return raw
    return None
