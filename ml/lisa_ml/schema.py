from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

IDLE = "IDLE"


@dataclass(frozen=True)
class Event:
    agent_id: int
    app: str
    activity_type: str
    timestamp: datetime
    duration_seconds: float | None = None
    role: str | None = None
    context: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: dict) -> Event:
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return cls(
            agent_id=row.get("agent_id"),
            app=row["app"],
            activity_type=row.get("activity_type", ""),
            timestamp=ts,
            duration_seconds=row.get("duration_seconds"),
            role=row.get("role"),
            context=row.get("context") or {},
        )
