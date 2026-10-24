"""Gather the signals we already store about one agent, for the behaviour
debugging assistant (#211).

The collector is deliberately dependency-free of the LLM: it turns the DB rows
(agent row, heartbeats, activity events, build error) into a plain `signals`
dict plus a list of deterministic `observations` (plain-language facts derived
from the signals). The LLM prompt is grounded in both; and when the LLM is
unavailable the observations are still useful on their own, so the operator
always gets something.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.models import ActivityEvent, Agent, AgentActivity, ApplicationTemplate

# How many recent rows of each kind to summarise.
_RECENT_HEARTBEATS = 15
_RECENT_EVENTS = 20


def _heartbeat_interval_seconds(agent: Agent) -> int:
    configured = (agent.config or {}).get("heartbeat", {}).get("interval_minutes")
    if isinstance(configured, int | float) and configured > 0:
        return int(configured * 60)
    return get_settings().heartbeat_interval_seconds


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _humanise(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def collect_signals(session: Session, agent: Agent) -> tuple[dict, list[str]]:
    """Return (signals, observations) for `agent`."""
    now = datetime.now(UTC)
    interval = _heartbeat_interval_seconds(agent)

    # last_seen may be stored naive (sqlite) — treat it as UTC for the delta.
    since_seen: float | None = None
    if agent.last_seen is not None:
        last_seen = agent.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        since_seen = (now - last_seen).total_seconds()

    heartbeats = (
        session.query(AgentActivity)
        .filter(AgentActivity.agent_id == agent.id, AgentActivity.activity_type == "heartbeat")
        .order_by(AgentActivity.timestamp.desc())
        .limit(_RECENT_HEARTBEATS)
        .all()
    )
    events = (
        session.query(ActivityEvent)
        .filter(ActivityEvent.agent_id == agent.id)
        .order_by(ActivityEvent.timestamp.desc())
        .limit(_RECENT_EVENTS)
        .all()
    )
    event_count = session.query(ActivityEvent).filter(ActivityEvent.agent_id == agent.id).count()

    config = agent.config or {}
    configured_apps = list(config.get("applications", []))
    missing_plugins = [
        name
        for name in configured_apps
        if session.query(ApplicationTemplate)
        .filter(ApplicationTemplate.name == name, ApplicationTemplate.is_active.is_(True))
        .first()
        is None
    ]

    build_error = (agent.version_info or {}).get("last_build_error")

    signals = {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "status": agent.status,
        "os_type": agent.os_type,
        "last_seen": _iso(agent.last_seen),
        "seconds_since_last_seen": int(since_seen) if since_seen is not None else None,
        "heartbeat_interval_seconds": interval,
        "last_activity": agent.last_activity,
        "build_error": build_error,
        "configured_applications": configured_apps,
        "applications_without_plugin": missing_plugins,
        "schedule": {
            "work_start": config.get("schedule", {}).get("work_start"),
            "work_end": config.get("schedule", {}).get("work_end"),
            "workdays": config.get("schedule", {}).get("workdays"),
        },
        "activity_event_count": event_count,
        "recent_heartbeats": [
            {
                "timestamp": _iso(hb.timestamp),
                "status": (hb.activity_data or {}).get("status"),
                "application": (hb.activity_data or {}).get("application"),
                "version": (hb.activity_data or {}).get("version"),
            }
            for hb in heartbeats
        ],
        "recent_events": [
            {
                "timestamp": _iso(ev.timestamp),
                "app": ev.app,
                "activity_type": ev.activity_type,
                "duration_seconds": ev.duration_seconds,
            }
            for ev in events
        ],
    }

    return signals, _observations(signals)


def _observations(signals: dict) -> list[str]:
    """Deterministic, plain-language facts derived from the signals. These both
    ground the LLM prompt and serve as the fallback when the LLM is down."""
    out: list[str] = []
    status = signals["status"]
    interval = signals["heartbeat_interval_seconds"]
    since = signals["seconds_since_last_seen"]

    if status == "failed":
        detail = signals.get("build_error")
        first_line = detail.strip().splitlines()[0] if detail else "no error captured"
        out.append(f"The agent's last build failed ({first_line}).")

    if signals["last_seen"] is None:
        if status not in ("configured", "building", "failed"):
            out.append("The agent has never sent a heartbeat.")
    elif since is not None and since > 3 * interval:
        out.append(
            f"The agent is stale: last heartbeat {_humanise(since)} ago, well past its "
            f"{_humanise(interval)} interval — it may have crashed or lost connectivity."
        )

    if signals["activity_event_count"] == 0 and status in ("active", "online", "ready"):
        out.append(
            "No activity events have been recorded — the agent isn't producing simulated "
            "activity even though it has checked in."
        )

    missing = signals["applications_without_plugin"]
    if missing:
        out.append(
            "These configured applications have no plugin, so the agent can't launch them: "
            + ", ".join(missing)
            + "."
        )

    bad_hb = {
        hb["status"]
        for hb in signals["recent_heartbeats"]
        if hb["status"] and hb["status"] not in ("active", "online", "received")
    }
    if bad_hb:
        out.append(
            "Recent heartbeats reported non-healthy status: " + ", ".join(sorted(bad_hb)) + "."
        )

    return out
