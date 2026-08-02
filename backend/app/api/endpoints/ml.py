import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.models import Agent
from app.models_store import get_store, restrict_model
from app.security import require_agent_token

router = APIRouter()


def _agent_applications(agent: Agent) -> list[str]:
    apps = (agent.config or {}).get("applications", [])
    return [app for app in apps if isinstance(app, str)]


def _agent_role(agent: Agent) -> str | None:
    if agent.role:
        return agent.role.name
    return (agent.config or {}).get("agent_info", {}).get("role")


def _sample(counts: dict[str, int], rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    apps = list(counts)
    return rng.choices(apps, weights=[counts[app] for app in apps], k=1)[0]


@router.get("/agents/{agent_id}/next-activity", dependencies=[Depends(require_agent_token)])
def next_activity(
    agent_id: str,
    current: str | None = Query(default=None),
    sample: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    applications = _agent_applications(agent)
    state = current or agent.last_activity
    model = get_store().for_role(_agent_role(agent))
    trimmed = restrict_model(model, applications) if model and applications else None

    counts = (trimmed or {}).get("counts", {}).get(state) if state else None
    if not counts:
        fallback = applications[0] if applications else get_settings().default_activity
        return {
            "agent_id": agent_id,
            "current": state,
            "next_activity": fallback,
            "activity_type": "use",
            "source": "fallback",
            "trained_on": None,
        }

    predicted = _sample(counts) if sample else max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    total = sum(counts.values())
    return {
        "agent_id": agent_id,
        "current": state,
        "next_activity": predicted,
        "activity_type": "use",
        "source": "model",
        "trained_on": trimmed.get("trained_on") if trimmed else None,
        "distribution": {app: round(n / total, 3) for app, n in counts.items()},
    }


@router.get("/ml/status")
def ml_status():
    store = get_store()
    shared = store.get("_shared")
    return {
        "models_dir": str(store.directory),
        "shared_loaded": shared is not None,
        "shared_states": len(shared.get("counts", {})) if shared else 0,
    }


@router.post("/ml/reload")
def ml_reload():
    store = get_store()
    store.clear()
    shared = store.get("_shared")
    return {
        "reloaded": shared is not None,
        "shared_states": len(shared.get("counts", {})) if shared else 0,
    }
