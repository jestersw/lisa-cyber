"""Operator-triggered deployment orchestration (#212).

The operator picks a built agent and a set of target hosts; this endpoint
records a Deployment and kicks off the Ansible backend in the background, then
reflects status back via the list/detail routes. The heavy lifting (running the
playbook, status transitions) lives in app.services.deploy so this module stays
a thin HTTP layer.

All routes require an operator token (wired in main.py).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.models import Agent, Deployment
from app.schemas import DeploymentResponse, DeployRequest
from app.services.deploy import runner
from app.services.deploy.inventory import InventoryError, render_inventory

log = logging.getLogger("lisa.deploy")

router = APIRouter()


@router.post("/agents/{agent_id}/deploy", response_model=DeploymentResponse)
def deploy_agent(
    agent_id: str,
    request: DeployRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Deployment:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.installer_url:
        # Nothing to push until the builder has produced an installer.
        raise HTTPException(
            status_code=409,
            detail="Agent has no build yet; build it before deploying.",
        )

    targets = [t.model_dump() for t in request.targets]
    backend_url = request.backend_url or get_settings().public_base_url
    try:
        inventory_text = render_inventory(agent_id, agent.os_type, targets)
    except InventoryError as exc:
        # Unsupported OS (e.g. windows, #200) or a target that slipped past the
        # schema — a client error, not a server fault.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    deployment = Deployment(
        agent_id=agent_id,
        backend="ansible",
        status="pending",
        targets={"targets": targets, "backend_url": backend_url, "force": request.force},
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)

    background_tasks.add_task(
        runner.run_deployment,
        deployment.id,
        inventory_text,
        backend_url=backend_url,
        force=request.force,
    )
    log.info("deployment %s queued for agent %s (%d hosts)", deployment.id, agent_id, len(targets))
    return deployment


@router.get("/agents/{agent_id}/deployments", response_model=list[DeploymentResponse])
def list_deployments(
    agent_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[Deployment]:
    return (
        db.query(Deployment)
        .filter(Deployment.agent_id == agent_id)
        .order_by(Deployment.created_at.desc(), Deployment.id.desc())
        .limit(limit)
        .all()
    )


@router.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
def get_deployment(deployment_id: int, db: Session = Depends(get_db)) -> Deployment:
    deployment = db.get(Deployment, deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment
