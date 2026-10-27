"""Live range view: compact, poll-friendly reads for the operator panel.

Two endpoints power the "range map" + activity feed:

- ``GET /live/fleet`` — one small row per agent (current app, role, status,
  last-seen) for the grid that lights up.
- ``GET /live/events`` — recent activity across the whole fleet, newest first,
  with an ``after`` cursor so the panel can poll for just what's new.

Both are operator-only (the router is mounted behind ``require_operator``). They
read the data the agent now reports (heartbeats -> ``last_activity``; activity
events -> ``activity_events``) and do no work beyond a single indexed query, so
they are cheap to poll every few seconds.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.models import ActivityEvent, Agent

router = APIRouter()


@router.get("/live/fleet")
def live_fleet(db: Session = Depends(get_db)):
    """Per-agent status for the range grid, in one query.

    ``current_app`` is the app from the agent's latest heartbeat; ``last_seen``
    lets the panel grey out agents we haven't heard from recently.
    """
    agents = db.query(Agent).options(joinedload(Agent.role)).order_by(Agent.agent_id).all()
    return {
        "agents": [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "role": a.role.name if a.role else None,
                "os_type": a.os_type,
                "status": a.status,
                "current_app": a.last_activity,
                "last_seen": a.last_seen.isoformat() if a.last_seen else None,
            }
            for a in agents
        ]
    }


@router.get("/live/events")
def live_events(
    after: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Recent fleet-wide activity, newest first, for the live feed.

    Pass the highest ``id`` you've already seen as ``after`` to get only newer
    events (cheap incremental polling); omit it for the initial page.
    ``latest_id`` echoes the newest id in this page so the caller can advance
    its cursor without re-scanning the list.
    """
    query = db.query(ActivityEvent).options(joinedload(ActivityEvent.agent))
    if after is not None:
        query = query.filter(ActivityEvent.id > after)
    rows = query.order_by(ActivityEvent.id.desc()).limit(limit).all()
    return {
        "events": [
            {
                "id": r.id,
                "agent_id": r.agent.agent_id if r.agent else None,
                "name": r.agent.name if r.agent else None,
                "app": r.app,
                "activity_type": r.activity_type,
                "role": r.role,
                "duration_seconds": r.duration_seconds,
                "context": r.context,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ],
        "latest_id": rows[0].id if rows else after,
    }
