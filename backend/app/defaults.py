from __future__ import annotations

import random


def _random_time(start_hour: int, end_hour: int, rng: random.Random) -> str:
    minutes = rng.randint(start_hour * 60, end_hour * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def default_schedule(rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    return {
        "workdays": [1, 2, 3, 4, 5],
        "work_start": _random_time(8, 10, rng),
        "work_end": _random_time(17, 19, rng),
        "lunch": {
            "earliest": "13:00",
            "latest": "15:00",
            "min_minutes": 45,
            "max_minutes": 75,
        },
    }


def default_behavior() -> dict:
    return {
        "session_duration": {"min": 300, "max": 900},
        "app_switch_pause": {"min": 30, "max": 120},
        "inactive_period": {"min": 10, "max": 20},
    }


def build_agent_config(
    agent_id: str,
    name: str,
    role: str,
    os_type: str,
    applications: list[str],
    overrides: dict | None = None,
    rng: random.Random | None = None,
) -> dict:
    overrides = overrides or {}
    schedule = overrides.get("schedule") or default_schedule(rng)
    behavior = overrides.get("behavior") or default_behavior()
    interval = overrides.get("heartbeat_interval_minutes") or 30
    return {
        "agent_info": {
            "agent_id": agent_id,
            "name": name,
            "role": role,
            "os_type": os_type,
        },
        "schedule": schedule,
        "behavior": behavior,
        "heartbeat": {"interval_minutes": interval},
        "applications": applications,
    }
