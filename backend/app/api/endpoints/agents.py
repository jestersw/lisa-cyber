import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.defaults import build_agent_config
from app.llm import generate_plugin
from app.models.models import (
    Agent,
    AgentActivity,
    ApplicationTemplate,
    BehaviorTemplate,
    Role,
)
from app.models_store import get_store, restrict_model
from app.schemas import (
    AgentConfig,
    AgentConfigSpec,
    AgentGenerateResponse,
    AgentResponse,
    DeploymentPackage,
)
from app.security import require_agent_token

router = APIRouter()


@router.post("/agents/generate", response_model=AgentGenerateResponse)
def generate_agent(config: AgentConfig, db: Session = Depends(get_db)):
    role = None
    if config.role_id is not None:
        role = db.query(Role).filter(Role.id == config.role_id, Role.is_active.is_(True)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

    role_name = config.role or (role.name if role else None)
    if not role_name:
        raise HTTPException(status_code=400, detail="role or role_id is required")

    template = None
    if config.template_id is not None:
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
    applications = config.applications or (
        template.template_data.get("applications_used", [])
        if template and template.template_data
        else []
    )
    overrides = {
        "schedule": config.schedule,
        "behavior": config.behavior,
        "heartbeat_interval_minutes": config.heartbeat_interval_minutes,
    }
    agent_config = build_agent_config(
        agent_id, config.name, role_name, config.os_type.value, applications, overrides
    )
    db_agent = Agent(
        agent_id=agent_id,
        name=config.name,
        role_id=config.role_id,
        template_id=config.template_id,
        os_type=config.os_type.value,
        injection_target=config.injection_target,
        config=agent_config,
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
            "role": role_name,
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
            "role": agent.role.name
            if agent.role
            else (agent.config or {}).get("agent_info", {}).get("role"),
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
    response_model=DeploymentPackage,
    dependencies=[Depends(require_agent_token)],
)
def get_agent_config(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    stored = agent.config or {}
    if "agent_info" in stored:
        agent_config = stored
    else:
        apps = (
            agent.template.template_data.get("applications_used", [])
            if agent.template and agent.template.template_data
            else []
        )
        role_name = agent.role.name if agent.role else "user"
        agent_config = build_agent_config(
            agent.agent_id, agent.name, role_name, agent.os_type, apps
        )

    plugins: dict[str, dict] = {}
    for name in agent_config.get("applications", []):
        plugin = (
            db.query(ApplicationTemplate)
            .filter(ApplicationTemplate.name == name, ApplicationTemplate.is_active.is_(True))
            .first()
        )
        if plugin:
            plugins[name] = plugin.template_config
            continue

        generated = generate_plugin(name, agent.os_type)
        if generated is None:
            continue

        db.add(
            ApplicationTemplate(
                name=name,
                display_name=generated.get("app_info", {}).get("display_name"),
                category=generated.get("app_info", {}).get("category"),
                template_config=generated,
                os_type=agent.os_type,
                author="llm",
            )
        )
        db.commit()
        plugins[name] = generated

    model = get_store().for_role(agent_config.get("agent_info", {}).get("role"))
    if model is not None:
        trimmed = restrict_model(model, agent_config.get("applications", []))
        if trimmed is not None:
            agent_config = {**agent_config, "transition_model": trimmed}

    return DeploymentPackage(
        agent_config=AgentConfigSpec(**agent_config),
        application_plugins=plugins,
    )
