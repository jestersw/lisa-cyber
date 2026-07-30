from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from lisa_ml.schema import Event

StateKey = Callable[[Event], str]


def hour_bucket(when: datetime) -> str:
    h = when.hour
    if h < 6:
        return "night"
    if h < 12:
        return "morning"
    if h < 18:
        return "afternoon"
    return "evening"


def state_app(event: Event) -> str:
    return event.app


def state_app_hour(event: Event) -> str:
    return f"{event.app}@{hour_bucket(event.timestamp)}"


def feature_row(event: Event, prev: Event | None) -> dict:
    return {
        "app": event.app,
        "activity_type": event.activity_type,
        "hour": event.timestamp.hour,
        "weekday": event.timestamp.weekday(),
        "duration_seconds": event.duration_seconds,
        "prev_app": prev.app if prev else None,
        "role": event.role,
    }


def _by_agent(events: Iterable[Event]) -> dict[int, list[Event]]:
    grouped: dict[int, list[Event]] = {}
    for event in events:
        grouped.setdefault(event.agent_id, []).append(event)
    for rows in grouped.values():
        rows.sort(key=lambda e: e.timestamp)
    return grouped


def build_transitions(
    events: Iterable[Event], state_key: StateKey = state_app
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for rows in _by_agent(events).values():
        for prev, nxt in zip(rows, rows[1:], strict=False):
            pairs.append((state_key(prev), nxt.app))
    return pairs


def feature_rows(events: Iterable[Event]) -> list[dict]:
    rows: list[dict] = []
    for agent_rows in _by_agent(events).values():
        prev: Event | None = None
        for event in agent_rows:
            rows.append(feature_row(event, prev))
            prev = event
    return rows
