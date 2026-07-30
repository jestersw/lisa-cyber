from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import ActivityEvent, Agent
from app.schemas import ActivityEventBatch, ActivityEventResponse
from app.security import require_agent_token

router = APIRouter()


@router.post(
    "/agents/{agent_id}/events",
    dependencies=[Depends(require_agent_token)],
)
def ingest_events(agent_id: str, batch: ActivityEventBatch, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    role_name = agent.role.name if agent.role else None
    for event in batch.events:
        db.add(
            ActivityEvent(
                agent_id=agent.id,
                app=event.app,
                activity_type=event.activity_type,
                role=event.role or role_name,
                duration_seconds=event.duration_seconds,
                context=event.context,
                timestamp=event.timestamp,
            )
        )
    db.commit()
    return {"agent_id": agent_id, "ingested": len(batch.events)}


@router.get("/agents/{agent_id}/events", response_model=list[ActivityEventResponse])
def list_agent_events(agent_id: str, limit: int = 100, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return (
        db.query(ActivityEvent)
        .filter(ActivityEvent.agent_id == agent.id)
        .order_by(desc(ActivityEvent.timestamp))
        .limit(limit)
        .all()
    )


@router.get("/events/export")
def export_events(
    since: datetime | None = None,
    limit: int = Query(default=10000, le=100000),
    db: Session = Depends(get_db),
):
    query = db.query(ActivityEvent)
    if since is not None:
        query = query.filter(ActivityEvent.timestamp >= since)
    rows = query.order_by(asc(ActivityEvent.timestamp)).limit(limit).all()
    return {
        "count": len(rows),
        "events": [
            {
                "agent_id": r.agent_id,
                "app": r.app,
                "activity_type": r.activity_type,
                "role": r.role,
                "duration_seconds": r.duration_seconds,
                "context": r.context,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ],
    }
