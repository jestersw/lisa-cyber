"""Runtime configuration for the LISA agent.

All settings come from environment variables so that nothing sensitive
(backend URL, auth token) is ever hardcoded in the source. See .env.example.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Hosts for which plaintext http:// is tolerated: the agent and backend are the
# same machine (local dev, the build smoke test), so nothing crosses a network.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host.strip("[]").lower() in _LOOPBACK_HOSTS


def validate_backend_url(url: str, *, allow_insecure: bool = False) -> None:
    """Require https for agent->backend traffic (#55).

    The agent sends its auth token and heartbeats to this URL, so plaintext
    http would expose them on the wire. https is always accepted; http is
    accepted only when talking to a loopback host (local dev / the build smoke
    test, where nothing leaves the machine) or when the operator has explicitly
    opted out with LISA_ALLOW_INSECURE_HTTP for a trusted closed network.
    Raises ValueError otherwise so a misconfigured agent fails fast at startup
    rather than leaking credentials silently.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return
    if scheme == "http":
        if allow_insecure or _is_loopback(parsed.hostname):
            return
        raise ValueError(
            f"insecure backend URL {url!r}: agent-to-backend traffic must use https "
            "(set LISA_ALLOW_INSECURE_HTTP=1 to override on a trusted, isolated network)"
        )
    raise ValueError(f"backend URL must be http or https, got {url!r}")


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
    heartbeat_interval_minutes: int = 30
    schedule: WorkSchedule = field(default_factory=WorkSchedule)

    @classmethod
    def from_env(cls) -> Config:
        backend_url = os.environ.get("LISA_BACKEND_URL", "http://localhost:8000")
        # Fail fast on a plaintext backend URL so tokens/heartbeats aren't sent
        # in the clear (#55); loopback and an explicit override are allowed.
        validate_backend_url(backend_url, allow_insecure=_env_truthy("LISA_ALLOW_INSECURE_HTTP"))
        return cls(
            backend_url=backend_url,
            auth_token=os.environ.get("LISA_AGENT_TOKEN"),
            heartbeat_interval_minutes=_int("LISA_HEARTBEAT_INTERVAL_MINUTES", 30),
            schedule=WorkSchedule(
                start=os.environ.get("LISA_WORK_START", "09:00"),
                end=os.environ.get("LISA_WORK_END", "18:00"),
            ),
        )
