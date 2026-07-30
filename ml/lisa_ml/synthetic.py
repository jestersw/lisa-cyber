from __future__ import annotations

import random
from datetime import datetime, timedelta

from lisa_ml.schema import IDLE, Event

_ROLE_APPS = {
    "dev": ["code", "firefox", "terminal", "slack", IDLE],
    "admin": ["terminal", "firefox", "monitoring", "slack", IDLE],
    "user": ["firefox", "libreoffice", "mail", "slack", IDLE],
}

_NEXT = {
    "code": ["terminal", "firefox", "code", IDLE],
    "terminal": ["code", "terminal", "monitoring", IDLE],
    "firefox": ["slack", "firefox", "mail", IDLE],
    "slack": ["firefox", "code", IDLE],
    "mail": ["firefox", "libreoffice", IDLE],
    "libreoffice": ["mail", "firefox", IDLE],
    "monitoring": ["terminal", "firefox", IDLE],
    IDLE: ["firefox", "code", "terminal"],
}


def generate_events(
    agents: int = 3, days: int = 5, per_day: int = 20, seed: int = 0
) -> list[Event]:
    rng = random.Random(seed)
    roles = list(_ROLE_APPS)
    events: list[Event] = []
    start = datetime(2026, 7, 6, 9, 0)
    for agent_id in range(1, agents + 1):
        role = roles[(agent_id - 1) % len(roles)]
        current = rng.choice(_ROLE_APPS[role])
        for day in range(days):
            when = start + timedelta(days=day)
            for _ in range(per_day):
                when += timedelta(minutes=rng.randint(5, 25))
                events.append(
                    Event(
                        agent_id=agent_id,
                        app=current,
                        activity_type="use",
                        timestamp=when,
                        duration_seconds=float(rng.randint(30, 600)),
                        role=role,
                    )
                )
                current = rng.choice(_NEXT.get(current, _ROLE_APPS[role]))
    return events
