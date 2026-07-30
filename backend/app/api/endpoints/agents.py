"""Agent lifecycle + the HTTP config endpoint the agent pulls instead of hitting the DB."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.models import Agent, AgentActivity, BehaviorTemplate, Role
from app.schemas import (
    AgentConfig,
    AgentConfigResponse,
    AgentGenerateResponse,
    AgentResponse,
)
from app.security import require_agent_token

router = APIRouter()


@router.post("/agents/generate", response_model=AgentGenerateResponse)
def generate_agent(config: AgentConfig, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == config.role_id, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    template = (
        db.query(BehaviorTemplate)
        .filter(BehaviorTemplate.id == config.template_id, BehaviorTemplate.is_active.is_(True))
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.os_type != config.os_type.value:
        raise HTTPException(
            status_code=400,
            detail=f"Template OS ({template.os_type}) != requested OS ({config.os_type.value})",
        )

    agent_id = f"USR{str(uuid.uuid4().int)[:7]}"
    db_agent = Agent(
        agent_id=agent_id,
        name=config.name,
        role_id=config.role_id,
        template_id=config.template_id,
        os_type=config.os_type.value,
        injection_target=config.injection_target,
        config=config.custom_config,
        status="configured",
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)

    return AgentGenerateResponse(
        agent_id=agent_id,
        message=f"Agent '{config.name}' configured",
        config={
            "agent_id": agent_id,
            "name": config.name,
            "os_type": config.os_type.value,
            "role": role.name,
            "template_id": config.template_id,
        },
        config_url=f"/api/agents/{agent_id}/config",
        status_url=f"/api/agents/{agent_id}/status",
    )


@router.get("/agents", response_model=list[AgentResponse])
def list_agents(
    status: str | None = None,
    os_type: str | None = None,
    role_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Agent)
    if status:
        query = query.filter(Agent.status == status)
    if os_type:
        query = query.filter(Agent.os_type == os_type)
    if role_id:
        query = query.filter(Agent.role_id == role_id)
    return query.order_by(desc(Agent.created_at)).offset(skip).limit(limit).all()


@router.get("/agents/{agent_id}/status")
def get_agent_status(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    recent = (
        db.query(AgentActivity)
        .filter(AgentActivity.agent_id == agent.id)
        .order_by(desc(AgentActivity.timestamp))
        .limit(10)
        .all()
    )
    return {
        "agent": {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "status": agent.status,
            "os_type": agent.os_type,
            "role": agent.role.name if agent.role else None,
            "template": agent.template.name if agent.template else None,
            "last_seen": agent.last_seen,
        },
        "recent_activities": [
            {"id": a.id, "type": a.activity_type, "data": a.activity_data, "timestamp": a.timestamp}
            for a in recent
        ],
    }


@router.get(
    "/agents/{agent_id}/config",
    response_model=AgentConfigResponse,
    dependencies=[Depends(require_agent_token)],
)
def get_agent_config(agent_id: str, db: Session = Depends(get_db)):
    """The agent pulls its role + behavior template over HTTP (no DB access on the agent)."""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    settings = get_settings()
    return AgentConfigResponse(
        agent_id=agent.agent_id,
        name=agent.name,
        os_type=agent.os_type,
        role={
            "name": agent.role.name if agent.role else None,
            "description": agent.role.description if agent.role else None,
            "category": agent.role.category if agent.role else None,
        },
        behavior_template=agent.template.template_data if agent.template else {},
        server_url=settings.public_base_url,
        heartbeat_interval=settings.heartbeat_interval_seconds,
        version="1.0",
    )
