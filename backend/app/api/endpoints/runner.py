"""Start/stop a server-side demo run of an agent (see services/sim_runner).

Operator-only. These let the panel launch an agent's activity with one button
instead of the terminal. The run is a simulation on the server for the live
view; the real agent is deployed via the installer or the Ansible flow.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Agent, ApplicationTemplate
from app.services.sim_runner import _activity_descriptor, registry

router = APIRouter()


def _build_apps(db: Session, agent: Agent) -> list[dict[str, Any]]:
    """Resolve the agent's applications to {name, activities[]} descriptors,
    reading each app's plugin from the catalog. Apps without a plugin still get
    a default action so they appear in the run."""
    stored = agent.config or {}
    names = stored.get("applications")
    if not names and agent.template and agent.template.template_data:
        names = agent.template.template_data.get("applications_used", [])
    names = names or []

    apps: list[dict[str, Any]] = []
    for name in names:
        plugin = (
            db.query(ApplicationTemplate)
            .filter(ApplicationTemplate.name == name, ApplicationTemplate.is_active.is_(True))
            .order_by((ApplicationTemplate.os_type == agent.os_type).desc())
            .first()
        )
        activities = []
        if plugin and plugin.template_config:
            activities = [
                _activity_descriptor(a) for a in plugin.template_config.get("activities", [])
            ]
        if not activities:
            activities = [{"category": "process", "detail": None, "name": "work"}]
        apps.append({"name": name, "activities": activities})
    return apps


def _get_agent(db: Session, agent_id: str) -> Agent:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/agents/{agent_id}/run")
def start_run(agent_id: str, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    apps = _build_apps(db, agent)
    if not apps:
        raise HTTPException(status_code=409, detail="Agent has no applications to run")
    role = agent.role.name if agent.role else None
    if not registry.start(agent.id, agent.agent_id, role, apps):
        raise HTTPException(status_code=409, detail="A demo run is already active for this agent")
    return registry.status(agent.agent_id)


@router.post("/agents/{agent_id}/run/stop")
def stop_run(agent_id: str, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    registry.stop(agent.agent_id)
    return registry.status(agent.agent_id)


@router.get("/agents/{agent_id}/run")
def run_status(agent_id: str, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    return registry.status(agent.agent_id)
