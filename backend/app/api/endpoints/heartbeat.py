"""Heartbeat: matches the agent's build_payload exactly.

The agent POSTs {agent_id, status, system_info, current_activity, statistics,
version}. We upsert the agent, record the heartbeat as an activity, and return a
`commands` list — the channel for future 'update available' / 'refresh config'.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.models import Agent, AgentActivity
from app.schemas import AgentHeartbeatRequest, AgentHeartbeatResponse
from app.security import require_agent_token

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.post(
    "/agents/heartbeat",
    response_model=AgentHeartbeatResponse,
    dependencies=[Depends(require_agent_token)],
)
def receive_heartbeat(hb: AgentHeartbeatRequest, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == hb.agent_id).first()
    if not agent:
        agent = Agent(
            agent_id=hb.agent_id,
            name=hb.system_info.get("hostname", hb.agent_id),
            status=hb.status,
            os_type=hb.system_info.get("platform", "unknown"),
            config={},
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

    agent.status = hb.status
    agent.last_seen = _utcnow()
    if hb.current_activity:
        agent.last_activity = hb.current_activity.get("application")
    if hb.version is not None:
        info = dict(agent.version_info or {})
        info["version"] = hb.version
        agent.version_info = info

    db.add(
        AgentActivity(
            agent_id=agent.id, activity_type="heartbeat", activity_data=hb.model_dump(mode="json")
        )
    )
    if hb.statistics:
        db.add(
            AgentActivity(
                agent_id=agent.id, activity_type="statistics", activity_data=hb.statistics
            )
        )
    db.commit()

    return AgentHeartbeatResponse(
        status="received",
        agent_id=hb.agent_id,
        timestamp=_utcnow(),
        message="Heartbeat processed",
        next_heartbeat_in=get_settings().heartbeat_interval_seconds,
        commands=[],  # future: {"type": "update", ...} / {"type": "refresh_config"}
    )


@router.get("/agents/{agent_id}/heartbeats")
def get_agent_heartbeats(agent_id: str, limit: int = 10, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    hbs = (
        db.query(AgentActivity)
        .filter(AgentActivity.agent_id == agent.id, AgentActivity.activity_type == "heartbeat")
        .order_by(desc(AgentActivity.timestamp))
        .limit(limit)
        .all()
    )
    return {
        "agent_id": agent_id,
        "status": agent.status,
        "last_seen": agent.last_seen,
        "heartbeats": [{"timestamp": h.timestamp, "data": h.activity_data} for h in hbs],
    }


@router.get("/agents-active")
def get_active_agents(threshold_minutes: int = 30, db: Session = Depends(get_db)):
    cutoff = _utcnow() - timedelta(minutes=threshold_minutes)
    agents = db.query(Agent).filter(Agent.last_seen >= cutoff, Agent.status == "active").all()
    return {
        "threshold_minutes": threshold_minutes,
        "active_count": len(agents),
        "agents": [
            {"agent_id": a.agent_id, "name": a.name, "last_seen": a.last_seen} for a in agents
        ],
    }
