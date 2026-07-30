"""Runtime configuration for the LISA agent.

All settings come from environment variables so that nothing sensitive
(backend URL, auth token) is ever hardcoded in the source. See .env.example.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class WorkSchedule:
    """When the simulated employee is 'at work'."""

    start: str = "09:00"  # HH:MM, local time
    end: str = "18:00"
    # Days the employee works: Mon=0 .. Sun=6. Default Mon-Fri.
    workdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    # Lunch break window; the exact start/length is randomised at runtime.
    lunch_earliest: str = "13:00"
    lunch_latest: str = "15:00"
    lunch_min_minutes: int = 45
    lunch_max_minutes: int = 75


@dataclass(frozen=True)
class Config:
    backend_url: str = "http://localhost:8000"
    # Auth token for talking to the backend. Never hardcode - read from env.
    auth_token: str | None = None
    heartbeat_interval_hours: int = 24
    schedule: WorkSchedule = field(default_factory=WorkSchedule)

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            backend_url=os.environ.get("LISA_BACKEND_URL", "http://localhost:8000"),
            auth_token=os.environ.get("LISA_AGENT_TOKEN"),
            heartbeat_interval_hours=_int("LISA_HEARTBEAT_INTERVAL_HOURS", 24),
            schedule=WorkSchedule(
                start=os.environ.get("LISA_WORK_START", "09:00"),
                end=os.environ.get("LISA_WORK_END", "18:00"),
            ),
        )
